package com.klab.lovelive.allstars.fovmod;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.ArrayList;
import java.util.List;

/** Adds a standard AAC gapless edit to this backend's finalized, nonfragmented MP4. */
public final class MP4Gapless {
    private static final int MAX_MOOV_BYTES=16*1024*1024;
    private static final long UINT32_MAX=0xffffffffL;
    private MP4Gapless() {}
    private static void check(boolean ok,String message) throws IOException {
        if (!ok) throw new IOException("AAC MP4 finalization: "+message);
    }
    private static final class Box {
        final int start,size,header; final String type;
        Box(int start,int size,int header,String type) { this.start=start; this.size=size; this.header=header; this.type=type; }
        int payload() { return start+header; }
        int end() { return start+size; }
    }
    /**
     * encodedAacFrames is the number of AAC-LC access units, each decoding to
     * 1024 PCM sample frames. logicalPcmFrames excludes encoder priming/padding.
     * Only the bounded moov metadata is read into memory; mdat stays in place.
     */
    public static void finalizeAac(File mp4,int sampleRate,long logicalPcmFrames,
            int encoderDelayFrames,long encodedAacFrames) throws IOException {
        check(sampleRate>=8000&&sampleRate<=96000&&logicalPcmFrames>0&&encoderDelayFrames>=0,
                "invalid PCM/priming configuration");
        check(encodedAacFrames>0&&encodedAacFrames<=UINT32_MAX&&encodedAacFrames<=Long.MAX_VALUE/1024,
                "invalid AAC access-unit count");
        long rawFrames=encodedAacFrames*1024;
        check(logicalPcmFrames<=rawFrames-encoderDelayFrames,"AAC stream does not contain the complete PCM tail");
        check(rawFrames-encoderDelayFrames-logicalPcmFrames<=Integer.MAX_VALUE,"AAC padding is too large");
        RandomAccessFile file=new RandomAccessFile(mp4,"rw");
        try {
            long length=file.length(),offset=0,moovOffset=-1; int moovSize=0,moovHeader=0,media=0;
            while (offset<length) {
                check(length-offset>=8,"truncated top-level box"); file.seek(offset);
                long size=file.readInt()&UINT32_MAX; String type=readType(file); int header=8;
                if (size==1) { check(length-offset>=16,"truncated extended box"); size=file.readLong(); header=16; }
                check(size>=header&&size<=length-offset,"invalid/zero-sized top-level box");
                check(!"moof".equals(type)&&!"mvex".equals(type),"fragmented MP4 is unsupported");
                if ("moov".equals(type)) {
                    check(moovOffset<0&&size<=MAX_MOOV_BYTES,"duplicate or oversized moov");
                    moovOffset=offset; moovSize=(int)size; moovHeader=header;
                }
                if ("mdat".equals(type)) media++;
                offset+=size;
            }
            check(offset==length&&moovOffset>=0&&media==1,"expected one finalized moov/mdat pair");
            byte[] old=new byte[moovSize]; file.seek(moovOffset); file.readFully(old);
            List<Box> children=boxes(old,moovHeader,old.length);
            Box mvhd=one(children,"mvhd"); long oldScale=timescale(old,mvhd);
            check(oldScale>0,"zero movie timescale");
            long gcd=gcd(oldScale,sampleRate),newScale=oldScale/gcd*sampleRate;
            check(newScale>0&&newScale<=Integer.MAX_VALUE&&newScale%oldScale==0,
                    "movie/sample timescales cannot be represented exactly");
            long movieFactor=newScale/oldScale,logicalTicks=scale(logicalPcmFrames,newScale/sampleRate);
            List<byte[]> tracks=new ArrayList<byte[]>(); int audioTracks=0; long movieDuration=0;
            for (Box child:children) if ("trak".equals(child.type)) {
                List<Box> track=boxes(old,child.payload(),child.end()); Box tkhd=one(track,"tkhd"),mdia=one(track,"mdia");
                List<Box> mediaChildren=boxes(old,mdia.payload(),mdia.end()); Box hdlr=one(mediaChildren,"hdlr");
                check(hdlr.end()-hdlr.payload()>=12,"short track handler");
                boolean audio="soun".equals(type(old,hdlr.payload()+8));
                long duration=audio?logicalTicks:scale(duration(old,tkhd),movieFactor);
                movieDuration=Math.max(movieDuration,duration);
                List<byte[]> rebuilt=new ArrayList<byte[]>();
                if (audio) {
                    audioTracks++; check(audioTracks==1,"multiple audio tracks");
                    for (Box part:track) check(!"edts".equals(part.type),"audio already has an edit list");
                    validateAudio(old,mediaChildren,sampleRate,encodedAacFrames,rawFrames);
                }
                for (Box part:track) {
                    if ("tkhd".equals(part.type)) rebuilt.add(headerDuration(old,part,duration,-1));
                    else if (audio&&"mdia".equals(part.type)) rebuilt.add(audioMedia(old,part,rawFrames));
                    else if ("edts".equals(part.type)) rebuilt.add(rescaleEdts(old,part,movieFactor));
                    else rebuilt.add(copy(old,part));
                }
                if (audio) rebuilt.add(edit(logicalTicks,encoderDelayFrames));
                tracks.add(box("trak",join(rebuilt)));
            }
            check(audioTracks==1,"missing AAC audio track");
            List<byte[]> rebuiltMovie=new ArrayList<byte[]>(); int trackIndex=0;
            for (Box child:children) {
                if ("mvhd".equals(child.type)) rebuiltMovie.add(headerDuration(old,child,movieDuration,newScale));
                else if ("trak".equals(child.type)) rebuiltMovie.add(tracks.get(trackIndex++));
                else { check(!"mvex".equals(child.type),"fragmented movie"); rebuiltMovie.add(copy(old,child)); }
            }
            byte[] replacement=box("moov",join(rebuiltMovie));
            check(replacement.length<=MAX_MOOV_BYTES,"rebuilt moov exceeds metadata bound");
            // Appending avoids moving media bytes or changing any stco/co64 offsets.
            // The original moov becomes a same-sized free box after the new one is durable.
            file.seek(length); file.write(replacement); file.getFD().sync();
            file.seek(moovOffset+4); file.write(new byte[]{'f','r','e','e'}); file.getFD().sync();
        } finally { file.close(); }
    }
    private static void validateAudio(byte[] data,List<Box> media,int rate,long count,long raw) throws IOException {
        Box mdhd=one(media,"mdhd"); check(timescale(data,mdhd)==rate,"audio timescale differs from PCM rate");
        check(duration(data,mdhd)==raw,"audio media duration differs from encoded AAC sample count");
        Box minf=one(media,"minf"); Box stbl=one(boxes(data,minf.payload(),minf.end()),"stbl");
        List<Box> table=boxes(data,stbl.payload(),stbl.end()); Box stsd=one(table,"stsd"),stsz=one(table,"stsz"),stts=one(table,"stts");
        check(stsd.end()-stsd.payload()>=16&&u32(data,stsd.payload()+4)==1,"expected one AAC sample description");
        List<Box> descriptions=boxes(data,stsd.payload()+8,stsd.end());
        check(descriptions.size()==1&&"mp4a".equals(descriptions.get(0).type),"audio description is not mp4a");
        int p=stsz.payload(); check(stsz.end()-p>=12&&u32(data,p+8)==count,"AAC sample table count differs");
        long fixed=u32(data,p+4),required=12+(fixed==0?count*4:0);
        check(required==stsz.end()-p,"malformed AAC sample-size table");
        p=stts.payload(); check(stts.end()-p>=8,"short AAC timing table");
        long entries=u32(data,p+4),samples=0,ticks=0;
        check(entries<=(stts.end()-p-8)/8&&8+entries*8==stts.end()-p,"malformed AAC timing table");
        for (int n=0;n<entries;n++) {
            long number=u32(data,p+8+n*8),delta=u32(data,p+12+n*8);
            check(number>0&&delta==1024,"AAC-LC access units must each span 1024 samples");
            samples+=number; ticks+=number*delta;
        }
        check(samples==count&&ticks==raw,"AAC timing table does not cover encoded frames");
    }
    private static byte[] audioMedia(byte[] data,Box mdia,long raw) throws IOException {
        List<byte[]> result=new ArrayList<byte[]>();
        for (Box child:boxes(data,mdia.payload(),mdia.end()))
            result.add("mdhd".equals(child.type)?headerDuration(data,child,raw,-1):copy(data,child));
        return box("mdia",join(result));
    }
    private static byte[] edit(long duration,int delay) throws IOException {
        byte[] payload=new byte[28]; put32(payload,0,0x01000000); put32(payload,4,1);
        put64(payload,8,duration); put64(payload,16,delay); put32(payload,24,0x00010000);
        return box("edts",box("elst",payload));
    }
    private static byte[] rescaleEdts(byte[] data,Box edts,long factor) throws IOException {
        List<Box> children=boxes(data,edts.payload(),edts.end()); Box elst=one(children,"elst");
        check(children.size()==1,"unknown edit-list contents"); int p=elst.payload(),version=version(data,elst);
        check(elst.end()-p>=8,"short edit list"); long count=u32(data,p+4); int stride=version==0?12:20;
        check(count<=(elst.end()-p-8)/stride&&8+count*stride==elst.end()-p,"malformed edit list");
        byte[] payload=new byte[8+(int)count*20]; put32(payload,0,(u32(data,p)&0x00ffffffL)|0x01000000L); put32(payload,4,count);
        for (int n=0;n<count;n++) {
            int at=p+8+n*stride,out=8+n*20;
            long duration=version==0?u32(data,at):u64(data,at),time=version==0?(int)u32(data,at+4):signed64(data,at+8);
            put64(payload,out,scale(duration,factor)); put64(payload,out+8,time);
            put32(payload,out+16,u32(data,at+(version==0?8:16)));
        }
        return box("edts",box("elst",payload));
    }
    private static long timescale(byte[] data,Box header) throws IOException {
        check(!"tkhd".equals(header.type),"track header has no timescale"); int v=version(data,header),p=header.payload();
        check(header.end()-p>=(v==0?20:32),"short media/movie header"); return u32(data,p+(v==0?12:20));
    }
    private static long duration(byte[] data,Box header) throws IOException {
        int v=version(data,header),p=header.payload(),at="tkhd".equals(header.type)?(v==0?20:28):(v==0?16:24);
        check(header.end()-p>=at+(v==0?4:8),"short duration header"); return v==0?u32(data,p+at):u64(data,p+at);
    }
    private static byte[] headerDuration(byte[] data,Box header,long duration,long timescale) throws IOException {
        check(duration>=0,"negative duration"); int v=version(data,header),p=header.payload(),length=header.end()-p;
        boolean track="tkhd".equals(header.type); int oldEnd=track?(v==0?24:36):(v==0?20:32);
        check(length>=oldEnd,"short duration header"); boolean wide=v==1||duration>UINT32_MAX;
        byte[] payload=new byte[length+(wide&&v==0?12:0)];
        if (wide&&v==0) {
            put32(payload,0,(u32(data,p)&0x00ffffffL)|0x01000000L);
            put64(payload,4,u32(data,p+4)); put64(payload,12,u32(data,p+8));
            if (track) { put32(payload,20,u32(data,p+12)); put32(payload,24,u32(data,p+16)); put64(payload,28,duration); }
            else { put32(payload,20,timescale<0?u32(data,p+12):timescale); put64(payload,24,duration); }
            System.arraycopy(data,p+oldEnd,payload,oldEnd+12,length-oldEnd);
        } else {
            System.arraycopy(data,p,payload,0,length); int at=track?(v==0?20:28):(v==0?16:24);
            if (v==0) put32(payload,at,duration); else put64(payload,at,duration);
            if (!track&&timescale>=0) put32(payload,v==0?12:20,timescale);
        }
        return box(header.type,payload);
    }
    private static int version(byte[] data,Box box) throws IOException {
        check(box.end()-box.payload()>=4,"missing full-box version"); int version=data[box.payload()]&255;
        check(version<=1,"unsupported version in "+box.type); return version;
    }
    private static long scale(long value,long factor) throws IOException {
        check(value>=0&&factor>0&&value<=Long.MAX_VALUE/factor,"duration overflow"); return value*factor;
    }
    private static long gcd(long a,long b) { while (b!=0) { long next=a%b; a=b; b=next; } return a; }
    private static List<Box> boxes(byte[] data,int start,int end) throws IOException {
        check(start>=0&&end<=data.length&&start<=end,"invalid child-box bounds"); List<Box> result=new ArrayList<Box>();
        while (start<end) {
            check(end-start>=8,"truncated metadata box"); long size=u32(data,start); int header=8;
            if (size==1) { check(end-start>=16,"short extended metadata box"); size=u64(data,start+8); header=16; }
            check(size>=header&&size<=end-start,"invalid metadata box size");
            result.add(new Box(start,(int)size,header,type(data,start+4))); start+=(int)size;
        }
        return result;
    }
    private static Box one(List<Box> boxes,String type) throws IOException {
        Box found=null; for (Box box:boxes) if (type.equals(box.type)) { check(found==null,"duplicate "+type); found=box; }
        check(found!=null,"missing "+type); return found;
    }
    private static byte[] copy(byte[] data,Box box) { byte[] copy=new byte[box.size]; System.arraycopy(data,box.start,copy,0,box.size); return copy; }
    private static byte[] join(List<byte[]> pieces) throws IOException {
        long size=0; for (byte[] piece:pieces) size+=piece.length; check(size<=MAX_MOOV_BYTES,"metadata allocation bound exceeded");
        ByteArrayOutputStream output=new ByteArrayOutputStream((int)size);
        for (byte[] piece:pieces) output.write(piece,0,piece.length); return output.toByteArray();
    }
    private static byte[] box(String type,byte[] payload) throws IOException {
        check(payload.length<=MAX_MOOV_BYTES-8,"metadata box exceeds allocation bound"); byte[] result=new byte[payload.length+8];
        put32(result,0,result.length); for (int n=0;n<4;n++) result[4+n]=(byte)type.charAt(n); System.arraycopy(payload,0,result,8,payload.length); return result;
    }
    private static String readType(RandomAccessFile file) throws IOException {
        byte[] type=new byte[4]; file.readFully(type); return new String(type,"ISO-8859-1");
    }
    private static String type(byte[] data,int at) throws IOException { check(at>=0&&data.length-at>=4,"short box type"); return new String(data,at,4,"ISO-8859-1"); }
    private static long u32(byte[] data,int at) throws IOException {
        check(at>=0&&data.length-at>=4,"short uint32"); return ((long)(data[at]&255)<<24)|((long)(data[at+1]&255)<<16)|((long)(data[at+2]&255)<<8)|(data[at+3]&255);
    }
    private static long signed64(byte[] data,int at) throws IOException { return (u32(data,at)<<32)|u32(data,at+4); }
    private static long u64(byte[] data,int at) throws IOException { long result=signed64(data,at); check(result>=0,"uint64 exceeds signed range"); return result; }
    private static void put32(byte[] data,int at,long value) { data[at]=(byte)(value>>>24); data[at+1]=(byte)(value>>>16); data[at+2]=(byte)(value>>>8); data[at+3]=(byte)value; }
    private static void put64(byte[] data,int at,long value) { put32(data,at,value>>>32); put32(data,at+4,value); }
}
