#include "android_mv_audio_provider.h"
extern "C" {
#include "mv_audio_codec/clhca.h"
}
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>

static const uint64_t SOURCE_LIMIT=64ull*1024*1024,PCM_LIMIT=96ull*1024*1024;
static const uint64_t SIFAS_HCA_KEY=6498535309877346413ull;
struct AmvAudioProvider { int fd;const unsigned char *pcm;uint64_t bytes;AmvAudioInfo info; };
struct Input { int fd;uint64_t size;struct stat before; };
struct Work { AmvAudioCancelled cancel;void *context;double deadline; };
struct Range { int fd;uint64_t base,size;uint16_t subkey; };
struct Sink { AmvAudioProvider *p;const AmvAudioSelection *selection;Work *work;AmvAudioError *error; };
static int fail(AmvAudioError *e,int code,const char *message) {
    if(e){e->code=code;snprintf(e->message,sizeof(e->message),"%s",message);}return 0;
}
static double now_seconds(){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;return (double)t.tv_sec+t.tv_nsec*1e-9;}
static int check(Work *w,AmvAudioError *e){
    if(w->cancel&&w->cancel(w->context))return fail(e,AMV_AUDIO_CANCELLED,"MV audio preparation was cancelled.");
    if(now_seconds()>w->deadline)return fail(e,AMV_AUDIO_LIMIT,"MV audio preparation exceeded its work limit.");
    return 1;
}
static uint16_t be16(const unsigned char *b){return (uint16_t)((b[0]<<8)|b[1]);}
static uint32_t be32(const unsigned char *b){return ((uint32_t)b[0]<<24)|((uint32_t)b[1]<<16)|((uint32_t)b[2]<<8)|b[3];}
static uint64_t le(const unsigned char *b,unsigned n){uint64_t v=0;for(unsigned i=0;i<n;i++)v|=(uint64_t)b[i]<<(8*i);return v;}
static int read_full(int fd,uint64_t at,void *destination,size_t bytes){
    unsigned char *out=(unsigned char *)destination;
    while(bytes){size_t wanted=bytes>65536?65536:bytes;ssize_t n=pread(fd,out,wanted,(off_t)at);
        if(n<0&&errno==EINTR)continue;
        if(n<=0)return 0;
        out+=n;bytes-=(size_t)n;at+=(uint64_t)n;}return 1;
}
static int range_read(const Range *r,uint64_t at,void *out,size_t bytes){return at<=r->size&&bytes<=r->size-at&&read_full(r->fd,r->base+at,out,bytes);}
static int input_open(Input *in,const char *path,AmvAudioError *e){
    in->fd=-1;in->size=0;
    if(!path||path[0]!='/'||!memchr(path,0,AMV_AUDIO_PATH_CAP))return fail(e,AMV_AUDIO_ARGUMENT,"The loaded song has no bounded absolute cache path.");
    in->fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    if(in->fd<0)return fail(e,AMV_AUDIO_SOURCE,"The loaded song cache file is unavailable.");
    if(fstat(in->fd,&in->before)||!S_ISREG(in->before.st_mode)||in->before.st_size<=0||(uint64_t)in->before.st_size>SOURCE_LIMIT)
        return fail(e,AMV_AUDIO_LIMIT,"The loaded song cache is not a bounded regular file.");
    in->size=(uint64_t)in->before.st_size;return 1;
}
static int input_unchanged(const Input *in){
    struct stat s;if(fstat(in->fd,&s))return 0;
    return s.st_dev==in->before.st_dev&&s.st_ino==in->before.st_ino&&s.st_size==in->before.st_size
        &&s.st_mtim.tv_sec==in->before.st_mtim.tv_sec&&s.st_mtim.tv_nsec==in->before.st_mtim.tv_nsec
        &&s.st_ctim.tv_sec==in->before.st_ctim.tv_sec&&s.st_ctim.tv_nsec==in->before.st_ctim.tv_nsec;
}
/* Only the one Header row's binary AwbFile column is needed for memory cues.
 * Follow the real @UTF offsets/storage flags; never scan for an AFS2 marker. */
static int utf_name(const Range *r,uint64_t strings,uint64_t data,uint32_t index,char out[64]){
    if(index>=data-strings)return 0;
    uint64_t at=strings+index;
    for(unsigned i=0;i<64;i++){unsigned char b;if(at+i>=data||!range_read(r,at+i,&b,1))return 0;out[i]=(char)b;if(!b)return 1;}return 0;
}
static int embedded_bank(const Input *acb,Range *bank,AmvAudioError *e){
    Range r={acb->fd,0,acb->size,0};unsigned char h[32];
    if(!range_read(&r,0,h,sizeof(h))||memcmp(h,"@UTF",4))return fail(e,AMV_AUDIO_FORMAT,"The memory cue has no supported CRI UTF header.");
    uint64_t end=(uint64_t)be32(h+4)+8,rows=(uint64_t)be16(h+10)+8,strings=(uint64_t)be32(h+12)+8,data=(uint64_t)be32(h+16)+8;
    unsigned columns=be16(h+24),row_width=be16(h+26);
    if(end>r.size||rows<32||rows>strings||strings>data||data>end||!columns||columns>512||be32(h+28)!=1||row_width>strings-rows)
        return fail(e,AMV_AUDIO_BANK,"The memory cue contains invalid UTF table bounds.");
    const unsigned widths[12]={1,1,2,2,4,4,8,8,4,8,4,8};uint64_t declaration=32,row_at=rows;int found=0;
    for(unsigned i=0;i<columns;i++){
        unsigned char column[5];if(declaration+5>rows||!range_read(&r,declaration,column,5))return fail(e,AMV_AUDIO_BANK,"The memory cue has truncated UTF columns.");
        declaration+=5;unsigned storage=column[0]&0xf0,kind=column[0]&15;
        if(kind>=12||(storage!=0x10&&storage!=0x30&&storage!=0x50))return fail(e,AMV_AUDIO_FORMAT,"The memory cue uses unsupported UTF storage.");
        unsigned width=widths[kind];uint64_t value_at=0;
        if(storage==0x30){if(width>rows-declaration)return fail(e,AMV_AUDIO_BANK,"The memory cue has truncated UTF constants.");value_at=declaration;declaration+=width;}
        if(storage==0x50){if(row_at>rows+row_width||width>rows+row_width-row_at)return fail(e,AMV_AUDIO_BANK,"The memory cue has truncated UTF row values.");value_at=row_at;row_at+=width;}
        char name[64];if(!utf_name(&r,strings,data,be32(column+1),name))return fail(e,AMV_AUDIO_BANK,"The memory cue has an invalid UTF column name.");
        if(strcmp(name,"AwbFile"))continue;
        if(found++||kind!=11||!value_at)return fail(e,AMV_AUDIO_BANK,"The memory cue has an ambiguous embedded audio bank.");
        unsigned char value[8];if(!range_read(&r,value_at,value,8))return fail(e,AMV_AUDIO_BANK,"The memory cue has a truncated embedded bank reference.");
        uint64_t base=data+be32(value),size=be32(value+4);
        if(base<data||base>end||!size||size>end-base)return fail(e,AMV_AUDIO_BANK,"The memory cue has an invalid embedded bank range.");
        bank->fd=acb->fd;bank->base=base;bank->size=size;bank->subkey=0;
    }
    if(!found)return fail(e,AMV_AUDIO_BANK,"The memory cue has no embedded AwbFile field.");
    return 1;
}
static int compare_ids(const void *a,const void *b){uint32_t x=*(const uint32_t *)a,y=*(const uint32_t *)b;return x<y?-1:x>y?1:0;}
static int select_wave(const Range *bank,uint32_t wanted,Range *wave,AmvAudioError *e){
    unsigned char h[16];if(!range_read(bank,0,h,16)||memcmp(h,"AFS2",4))return fail(e,AMV_AUDIO_BANK,"The selected song has no supported AFS2 audio bank.");
    unsigned offset_width=h[5],id_width=h[6];uint32_t count=(uint32_t)le(h+8,4);uint64_t alignment=le(h+12,2);
    if((offset_width!=2&&offset_width!=4&&offset_width!=8)||(id_width!=2&&id_width!=4)||!count||count>65536||!alignment)
        return fail(e,AMV_AUDIO_BANK,"The selected song has invalid AWB entry metadata.");
    uint64_t table_size=16+(uint64_t)count*id_width+((uint64_t)count+1)*offset_width;
    if(table_size>bank->size)return fail(e,AMV_AUDIO_BANK,"The selected song has a truncated AWB table.");
    unsigned char *table=(unsigned char *)malloc((size_t)table_size);uint32_t *ids=(uint32_t *)malloc((size_t)count*sizeof(uint32_t));
    if(!table||!ids){free(table);free(ids);return fail(e,AMV_AUDIO_MEMORY,"The AWB entry table could not be allocated.");}
    int ok=range_read(bank,0,table,(size_t)table_size),found=0;uint64_t offsets=16+(uint64_t)count*id_width;
    for(uint32_t i=0;ok&&i<count;i++){
        ids[i]=(uint32_t)le(table+16+(uint64_t)i*id_width,id_width);
        uint64_t begin=le(table+offsets+(uint64_t)i*offset_width,offset_width),end=le(table+offsets+((uint64_t)i+1)*offset_width,offset_width);
        if(begin>bank->size||end>bank->size){ok=0;break;}
        begin=(begin+alignment-1)/alignment*alignment;
        if(begin<table_size||begin>=end){ok=0;break;}
        if(ids[i]==wanted){wave->fd=bank->fd;wave->base=bank->base+begin;wave->size=end-begin;wave->subkey=(uint16_t)le(h+14,2);found++;}
    }
    if(ok){qsort(ids,count,sizeof(uint32_t),compare_ids);for(uint32_t i=1;i<count;i++)if(ids[i]==ids[i-1]){ok=0;break;}}
    free(table);free(ids);
    if(!ok)return fail(e,AMV_AUDIO_BANK,"The selected song AWB contains corrupt ranges or duplicate wave IDs.");
    if(found!=1)return fail(e,AMV_AUDIO_BANK,"The exact selected waveform ID is missing or ambiguous in the AWB.");
    return 1;
}
static int64_t round_sample_ms(int32_t ms,uint32_t rate){int64_t n=(int64_t)ms*rate;return n<0?-((-n+500)/1000):(n+500)/1000;}
static int32_t round_even(double n){double low=floor(n),part=n-low;int32_t v=(int32_t)low;if(part>.5||(part==.5&&(v&1)))v++;return v;}
static int sink_pcm(Sink *s,uint64_t source_at,uint32_t count,const int16_t *samples){
    if(!check(s->work,s->error))return 0;
    int64_t start=s->p->info.start_sample,offset=s->p->info.source_offset_samples;
    uint64_t source_min=(uint64_t)(offset+(start<0?-start:0));
    int64_t source_end=(int64_t)s->p->info.audio_frames-start+offset;
    uint64_t first=source_at>source_min?source_at:source_min,last=source_at+count;
    if(source_end<0||first>=(uint64_t)source_end)return 1;
    if(last>(uint64_t)source_end)last=(uint64_t)source_end;
    if(first>=last)return 1;
    uint32_t channels=s->p->info.channels,n=(uint32_t)(last-first);int16_t adjusted[2048];
    if(n>1024)return fail(s->error,AMV_AUDIO_LIMIT,"The decoder exceeded its bounded PCM block size.");
    const int16_t *pcm=samples+(first-source_at)*channels;
    if(s->selection->gain!=1){for(uint32_t i=0;i<n*channels;i++){int32_t v=round_even((double)pcm[i]*s->selection->gain);adjusted[i]=(int16_t)(v<-32768?-32768:v>32767?32767:v);}pcm=adjusted;}
    uint64_t destination=(uint64_t)((int64_t)first-offset+start)*channels*2;size_t bytes=(size_t)n*channels*2;const unsigned char *data=(const unsigned char *)pcm;
    while(bytes){ssize_t written=pwrite(s->p->fd,data,bytes,(off_t)destination);if(written<0&&errno==EINTR)continue;
        if(written<=0)return fail(s->error,errno==ENOSPC?AMV_AUDIO_SPACE:AMV_AUDIO_IO,"The private MV PCM file could not be written.");
        data+=written;bytes-=(size_t)written;destination+=(uint64_t)written;}return 1;
}
static int codec_metadata(Sink *s,uint32_t rate,uint32_t channels,uint64_t frames){
    if(rate!=s->selection->sample_rate||channels!=s->selection->channels||!frames||frames>1200ull*rate||frames*channels*2>PCM_LIMIT)
        return fail(s->error,AMV_AUDIO_FORMAT,"The codec PCM format does not match the selected CRI waveform.");
    return 1;
}
static int decode_hca(const Range *wave,Sink *sink){
    unsigned char prefix[8];if(!range_read(wave,0,prefix,8))return fail(sink->error,AMV_AUDIO_FORMAT,"The HCA header is truncated.");
    int header_size=clHCA_isOurFile(prefix,8);if(header_size<8||header_size>65535||(uint64_t)header_size>wave->size)return fail(sink->error,AMV_AUDIO_FORMAT,"The selected HCA header is unsupported.");
    unsigned char *header=(unsigned char *)malloc((size_t)header_size);clHCA *decoder=clHCA_new();unsigned char *block=NULL;int ok=0;clHCA_stInfo info;memset(&info,0,sizeof(info));
    if(!header||!decoder){fail(sink->error,AMV_AUDIO_MEMORY,"The HCA decoder state could not be allocated.");goto done;}
    {uint64_t key=SIFAS_HCA_KEY;if(wave->subkey)key*=((uint32_t)wave->subkey<<16)|((~wave->subkey+2)&0xffff);clHCA_SetKey(decoder,key);}
    if(!range_read(wave,0,header,(size_t)header_size)||clHCA_DecodeHeader(decoder,header,(unsigned)header_size)<0||clHCA_getInfo(decoder,&info)<0){fail(sink->error,AMV_AUDIO_CRYPT,"The HCA header, codec version or encryption is unsupported.");goto done;}
    {uint64_t total=(uint64_t)info.blockCount*1024,trim=(uint64_t)info.encoderDelay+info.encoderPadding;
        if(info.samplesPerBlock!=1024||trim>=total||info.loopEnabled||!info.blockSize||info.blockSize>65535||(uint64_t)info.headerSize+(uint64_t)info.blockSize*info.blockCount>wave->size
                ||!codec_metadata(sink,info.samplingRate,info.channelCount,total-trim)){if(!sink->error||!sink->error->code)fail(sink->error,AMV_AUDIO_FORMAT,"The selected HCA waveform uses unsupported loop or frame bounds.");goto done;}
        if(sink->selection->source_samples!=total-trim){fail(sink->error,AMV_AUDIO_FORMAT,"The decoded HCA sample count does not match the selected CRI waveform.");goto done;}
        block=(unsigned char *)malloc(info.blockSize);if(!block){fail(sink->error,AMV_AUDIO_MEMORY,"The bounded HCA block could not be allocated.");goto done;}
        for(uint32_t i=0;i<info.blockCount;i++){
            if(!check(sink->work,sink->error))goto done;
            if(!range_read(wave,info.headerSize+(uint64_t)i*info.blockSize,block,info.blockSize)||clHCA_DecodeBlock(decoder,block,info.blockSize)<0){fail(sink->error,AMV_AUDIO_CRYPT,"The selected HCA block is corrupt or its encryption key is unsupported.");goto done;}
            int16_t samples[2048];clHCA_ReadSamples16(decoder,samples);
            uint64_t base=(uint64_t)i*1024;uint32_t first=base<info.encoderDelay?(uint32_t)(info.encoderDelay-base):0;
            uint64_t last_absolute=base+1024<total-info.encoderPadding?base+1024:total-info.encoderPadding;
            if(first<1024&&last_absolute>base+first&&!sink_pcm(sink,base+first-info.encoderDelay,(uint32_t)(last_absolute-base-first),samples+first*info.channelCount))goto done;
        }
        sink->p->info.source_frames=total-trim;sink->p->info.decoder=1;ok=1;}
done: free(header);free(block);if(decoder)clHCA_delete(decoder);return ok;
}
static int64_t floor_div_4096(int64_t n){return n>=0?n/4096:-((-n+4095)/4096);}
static int decode_adx(const Range *wave,Sink *sink){
    unsigned char h[24],copyright[6];if(!range_read(wave,0,h,sizeof(h)))return fail(sink->error,AMV_AUDIO_FORMAT,"The ADX header is truncated.");
    uint32_t header=(uint32_t)be16(h+2)+4,channels=h[7],rate=be32(h+8),frames=be32(h+12),cutoff=be16(h+16);
    if(h[19])return fail(sink->error,AMV_AUDIO_CRYPT,"Encrypted ADX is not supported by the selected song decoder.");
    if(be16(h)!=0x8000||header<24||header>wave->size||h[4]!=3||h[5]!=18||h[6]!=4||!range_read(wave,header-6,copyright,6)||memcmp(copyright,"(c)CRI",6)
            ||!codec_metadata(sink,rate,channels,frames)||cutoff>=rate/2)
        return fail(sink->error,AMV_AUDIO_FORMAT,"The selected ADX encoding or frame metadata is unsupported.");
    if(sink->selection->source_samples!=frames&&sink->selection->source_samples+32!=frames)return fail(sink->error,AMV_AUDIO_FORMAT,"The ADX sample count does not match the selected CRI waveform.");
    double a=sqrt(2.)-cos(2.*3.14159265358979323846*cutoff/rate),b=sqrt(2.)-1.,c=(a-sqrt((a+b)*(a-b)))/b;
    int32_t first=round_even((float)(c*2.*4096)),second=round_even((float)(-c*c*4096));int32_t history[2][2]={{0,0},{0,0}};uint64_t actual=0;
    for(uint32_t block=0;actual<frames;block++){
        if(!check(sink->work,sink->error))return 0;
        unsigned char raw[36];uint64_t at=header+(uint64_t)block*channels*18;
        unsigned char marker[2];if(!range_read(wave,at,marker,2))return fail(sink->error,AMV_AUDIO_FORMAT,"The selected ADX waveform has truncated blocks.");
        if(marker[0]&0x80){if(frames-actual>32)return fail(sink->error,AMV_AUDIO_FORMAT,"The selected ADX waveform ends before its declared samples.");break;}
        if(!range_read(wave,at,raw,channels*18))return fail(sink->error,AMV_AUDIO_FORMAT,"The selected ADX waveform has truncated channel blocks.");
        uint32_t count=frames-actual<32?(uint32_t)(frames-actual):32;int16_t pcm[64];
        for(uint32_t ch=0;ch<channels;ch++){
            const unsigned char *data=raw+ch*18;int32_t scale=be16(data);if(scale&0x8000)return fail(sink->error,AMV_AUDIO_FORMAT,"The ADX channels end at different samples.");
            int32_t previous=history[ch][0],before=history[ch][1];
            for(uint32_t i=0;i<32;i++){int residual=i&1?data[2+i/2]&15:data[2+i/2]>>4;if(residual>=8)residual-=16;
                int64_t value=(int64_t)residual*scale+floor_div_4096((int64_t)first*previous+(int64_t)second*before);
                if(value<-32768)value=-32768;
                if(value>32767)value=32767;
                before=previous;previous=(int32_t)value;
                if(i<count)pcm[i*channels+ch]=(int16_t)value;}
            history[ch][0]=previous;history[ch][1]=before;
        }
        if(!sink_pcm(sink,actual,count,pcm))return 0;
        actual+=count;
    }
    if(!actual||(sink->selection->source_samples!=actual&&sink->selection->source_samples!=frames))return fail(sink->error,AMV_AUDIO_FORMAT,"The selected ADX source has no matching decoded samples.");
    sink->p->info.source_frames=actual;sink->p->info.decoder=2;return 1;
}
static int prepare_inner(AmvAudioProvider *p,const AmvAudioSelection *s,const char *cache,uint64_t video,uint32_t num,uint32_t den,Work *work,AmvAudioError *e){
    Input acb,awb;acb.fd=awb.fd=-1;acb.size=awb.size=0;Range bank={-1,0,0,0},wave={-1,0,0,0};int ok=0;char resolved[PATH_MAX],temporary[PATH_MAX];struct stat dir;struct statvfs capacity;
    if(!check(work,e))return 0;
    if(!input_open(&acb,s->acb_path,e))goto done;
    if(s->streaming){if(!input_open(&awb,s->awb_path,e))goto done;if(acb.size+awb.size>SOURCE_LIMIT){fail(e,AMV_AUDIO_LIMIT,"The selected song exceeds the aggregate source byte limit.");goto done;}bank.fd=awb.fd;bank.base=0;bank.size=awb.size;}
    else if(!embedded_bank(&acb,&bank,e))goto done;
    if(!select_wave(&bank,s->wave_id,&wave,e))goto done;
    if(!realpath(cache,resolved)||strcmp(cache,resolved)||stat(resolved,&dir)||!S_ISDIR(dir.st_mode)){fail(e,AMV_AUDIO_ARGUMENT,"MV audio needs an existing canonical private cache directory.");goto done;}
    p->info.abi_version=AMV_AUDIO_ABI;p->info.sample_rate=s->sample_rate;p->info.channels=s->channels;p->info.bytes_per_frame=s->channels*2;p->info.wave_id=s->wave_id;
    p->info.audio_frames=(video*den*s->sample_rate+num-1)/num;p->bytes=p->info.audio_frames*p->info.bytes_per_frame;
    p->info.start_sample=round_sample_ms(s->start_time_ms,s->sample_rate);p->info.source_offset_samples=round_sample_ms(s->source_offset_ms,s->sample_rate);
    if(p->bytes>PCM_LIMIT){fail(e,AMV_AUDIO_LIMIT,"The MV export exceeds the PCM byte limit.");goto done;}
    if(statvfs(resolved,&capacity)||!capacity.f_frsize||capacity.f_bavail<(p->bytes+1024*1024+capacity.f_frsize-1)/capacity.f_frsize){fail(e,AMV_AUDIO_SPACE,"There is not enough private cache space for the selected MV audio.");goto done;}
    if(snprintf(temporary,sizeof(temporary),"%s/.mv-audio-XXXXXX",resolved)>=(int)sizeof(temporary)){fail(e,AMV_AUDIO_ARGUMENT,"The private MV cache directory path is too long.");goto done;}
    p->fd=mkstemp(temporary);if(p->fd<0){fail(e,AMV_AUDIO_IO,"The private MV PCM file could not be created.");goto done;}
    if(unlink(temporary)){close(p->fd);p->fd=-1;fail(e,AMV_AUDIO_IO,"The private MV PCM file could not acquire anonymous ownership.");goto done;}
    if(fcntl(p->fd,F_SETFD,FD_CLOEXEC)||ftruncate(p->fd,(off_t)p->bytes)){fail(e,errno==ENOSPC?AMV_AUDIO_SPACE:AMV_AUDIO_IO,"The private MV PCM file could not be sized.");goto done;}
    {Sink sink={p,s,work,e};unsigned char signature[4];if(!range_read(&wave,0,signature,4)){fail(e,AMV_AUDIO_FORMAT,"The selected waveform is truncated.");goto done;}
        for(unsigned i=0;i<4;i++)signature[i]&=0x7f;
        if(!memcmp(signature,"HCA\0",4)){if(!decode_hca(&wave,&sink))goto done;}
        else{unsigned char marker[2];if(!range_read(&wave,0,marker,2)||marker[0]!=0x80||marker[1]!=0){fail(e,AMV_AUDIO_FORMAT,"The selected waveform codec is unsupported.");goto done;}if(!decode_adx(&wave,&sink))goto done;}}
    {int64_t first=p->info.source_offset_samples+(p->info.start_sample<0?-p->info.start_sample:0),output=p->info.start_sample>0?p->info.start_sample:0;
        if(first>=(int64_t)p->info.source_frames||output>=(int64_t)p->info.audio_frames){fail(e,AMV_AUDIO_FORMAT,"The selected song has no samples within the export clock.");goto done;}}
    if(!input_unchanged(&acb)||(awb.fd>=0&&!input_unchanged(&awb))){fail(e,AMV_AUDIO_CHANGED,"The selected game audio cache changed during preparation.");goto done;}
    p->pcm=(const unsigned char *)mmap(NULL,(size_t)p->bytes,PROT_READ,MAP_PRIVATE,p->fd,0);
    if(p->pcm==MAP_FAILED){p->pcm=NULL;fail(e,AMV_AUDIO_MEMORY,"The prepared PCM could not be mapped for immutable playback.");goto done;}
    {long page=sysconf(_SC_PAGESIZE);if(page<=0)page=4096;volatile unsigned char touched=0;
        for(uint64_t at=0;at<p->bytes;at+=(uint64_t)page){if((at&((1u<<20)-1))==0&&!check(work,e))goto done;touched^=p->pcm[at];}(void)touched;}
    ok=check(work,e);
done:if(acb.fd>=0)close(acb.fd);if(awb.fd>=0)close(awb.fd);return ok;
}
extern "C" int amv_audio_prepare(const AmvAudioSelection *s,const char *cache,uint64_t video,uint32_t num,uint32_t den,AmvAudioCancelled cancel,void *context,AmvAudioProvider **out,AmvAudioError *e){
    if(e)memset(e,0,sizeof(*e));
    if(out)*out=NULL;
    uint16_t endian=1;
    if(!s||!cache||!out||s->abi_version!=AMV_AUDIO_ABI||s->streaming>1||(s->sample_rate!=44100&&s->sample_rate!=48000)||(s->channels!=1&&s->channels!=2)
            ||!s->source_samples||s->source_samples>1200ull*s->sample_rate||s->source_samples*s->channels*2>PCM_LIMIT||!(s->gain>=0&&s->gain<=4)
            ||s->music_length_ms<=0||s->music_length_ms>1200000||s->start_time_ms< -1200000||s->start_time_ms>1200000||s->source_offset_ms<0||s->source_offset_ms>1200000
            ||!video||video>144000||!num||num>120000||!den||den>1001||num<den||num>120*den||video*den>1200ull*num||*(unsigned char *)&endian!=1)
        return fail(e,AMV_AUDIO_ARGUMENT,"The verified native MV audio selection or export clock is invalid.");
    AmvAudioProvider *p=(AmvAudioProvider *)calloc(1,sizeof(*p));if(!p)return fail(e,AMV_AUDIO_MEMORY,"The MV audio session could not be allocated.");p->fd=-1;
    Work work={cancel,context,now_seconds()+90.};if(!prepare_inner(p,s,cache,video,num,den,&work,e)){amv_audio_close(p);return 0;}*out=p;return 1;
}
extern "C" int amv_audio_get_info(const AmvAudioProvider *p,AmvAudioInfo *out){if(!p||!out)return 0;*out=p->info;return 1;}
extern "C" int amv_audio_read_at(const AmvAudioProvider *p,uint64_t first,uint32_t count,int16_t *out){
    if(!p||!p->pcm||count>8192||first>p->info.audio_frames||count>p->info.audio_frames-first||(!out&&count))return -1;
    if(count)memcpy(out,p->pcm+first*p->info.bytes_per_frame,(size_t)count*p->info.bytes_per_frame);
    return (int)count;
}
extern "C" void amv_audio_close(AmvAudioProvider *p){if(!p)return;if(p->pcm)munmap((void *)p->pcm,(size_t)p->bytes);if(p->fd>=0)close(p->fd);free(p);}
