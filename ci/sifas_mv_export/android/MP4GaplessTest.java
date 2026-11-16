package com.klab.lovelive.allstars.fovmod;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.util.Arrays;

/** Host structural tests: synthetic boxes only; actual codec evidence is separate. */
public final class MP4GaplessTest {
    private static int checks;
    private static void check(boolean ok,String detail) { checks++; if (!ok) throw new AssertionError(detail); }
    private static ByteBuffer bytes(byte[] data) { return ByteBuffer.wrap(data).order(ByteOrder.BIG_ENDIAN); }
    private static byte[] concat(byte[]... pieces) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream(); for (byte[] p:pieces) out.write(p); return out.toByteArray();
    }
    private static byte[] box(String type,byte[] payload) throws Exception {
        ByteBuffer b=ByteBuffer.allocate(payload.length+8).order(ByteOrder.BIG_ENDIAN); b.putInt(b.capacity()); b.put(type.getBytes("US-ASCII")); b.put(payload); return b.array();
    }
    private static byte[] header(String type,int scale,int duration,int track) throws Exception {
        byte[] p=new byte[type.equals("tkhd")?84:100]; ByteBuffer b=bytes(p);
        b.putInt(4,1); b.putInt(8,2);
        if (type.equals("tkhd")) { b.putInt(12,track); b.putInt(20,duration); }
        else { b.putInt(12,scale); b.putInt(16,duration); }
        return box(type,p);
    }
    private static byte[] handler(String type) throws Exception {
        byte[] p=new byte[24]; System.arraycopy(type.getBytes("US-ASCII"),0,p,8,4); return box("hdlr",p);
    }
    private static byte[] timing(int count,int delta) throws Exception {
        byte[] p=new byte[16]; bytes(p).putInt(4,1).putInt(8,count).putInt(12,delta); return box("stts",p);
    }
    private static byte[] fixture(int rate,int packets,int delta,int videoDuration,boolean wideTop) throws Exception {
        byte[] sizes=new byte[12]; bytes(sizes).putInt(4,512).putInt(8,packets);
        byte[] descriptions=new byte[8]; bytes(descriptions).putInt(4,1);
        byte[] offsets=new byte[16]; bytes(offsets).putInt(4,1).putLong(8,0x1122334455667788L);
        byte[] audioTable=box("stbl",concat(box("stsd",concat(descriptions,box("mp4a",new byte[28]))),
                box("stsz",sizes),timing(packets,delta),box("co64",offsets)));
        byte[] audio=box("trak",concat(header("tkhd",0,packets*1024*10000/rate,2),
                box("mdia",concat(header("mdhd",rate,packets*1024,0),handler("soun"),box("minf",audioTable)))));
        byte[] video=box("trak",concat(header("tkhd",0,videoDuration,1),
                box("mdia",concat(header("mdhd",90000,180000,0),handler("vide"),box("zzzz",new byte[]{9,8,7,6})))));
        byte[] moov=box("moov",concat(header("mvhd",10000,Math.max(videoDuration,20480),0),video,audio,box("udta",new byte[]{1,3,5,7})));
        if (wideTop) {
            byte[] extended=new byte[moov.length+8]; ByteBuffer b=bytes(extended); b.putInt(1); b.put("moov".getBytes("US-ASCII")); b.putLong(extended.length); b.put(moov,8,moov.length-8); moov=extended;
        }
        byte[] media=new byte[48]; ByteBuffer b=bytes(media); b.putInt(1); b.put("mdat".getBytes("US-ASCII")); b.putLong(media.length);
        for (int n=16;n<media.length;n++) media[n]=(byte)n;
        return concat(box("ftyp",new byte[16]),moov,box("free",new byte[16]),media);
    }
    private static int find(byte[] d,int start,int end,String type) throws Exception {
        for (int p=start;p<end;) { long size=bytes(d).getInt(p)&0xffffffffL; int h=8;
            if (size==1) { size=bytes(d).getLong(p+8); h=16; }
            String found=new String(d,p+4,4,"US-ASCII"); if (found.equals(type)) return p;
            if (size<h||size>end-p) throw new AssertionError("Invalid test box"); p+=(int)size;
        }
        throw new AssertionError("Missing test box "+type);
    }
    private static int end(byte[] d,int at) { int size=bytes(d).getInt(at); return size==1?at+(int)bytes(d).getLong(at+8):at+size; }
    private static int payload(byte[] d,int at) { return at+(bytes(d).getInt(at)==1?16:8); }
    private static int child(byte[] d,int at,String type) throws Exception { return find(d,payload(d,at),end(d,at),type); }
    private static int track(byte[] d,int moov,String type) throws Exception {
        for (int p=payload(d,moov);p<end(d,moov);p=end(d,p)) if (new String(d,p+4,4,"US-ASCII").equals("trak")) {
            int mdia=child(d,p,"mdia"),hdlr=child(d,mdia,"hdlr"); if (new String(d,payload(d,hdlr)+8,4,"US-ASCII").equals(type)) return p;
        }
        throw new AssertionError("Missing track "+type);
    }
    private static long duration(byte[] d,int at,boolean track) {
        int p=payload(d,at),v=d[p]&255,offset=track?(v==0?20:28):(v==0?16:24);
        return v==0?(bytes(d).getInt(p+offset)&0xffffffffL):bytes(d).getLong(p+offset);
    }
    private static byte[] part(byte[] d,int at) { return Arrays.copyOfRange(d,at,end(d,at)); }
    private static void success(File directory,int rate,int videoDuration,boolean wide) throws Exception {
        File file=new File(directory,"success-"+rate+"-"+wide+".mp4"); byte[] original=fixture(rate,96,1024,videoDuration,wide); Files.write(file.toPath(),original);
        int oldMoov=find(original,0,original.length,"moov"),oldMdat=find(original,0,original.length,"mdat"),oldVideo=track(original,oldMoov,"vide");
        MP4Gapless.finalizeAac(file,rate,96001,2048,96); byte[] updated=Files.readAllBytes(file.toPath());
        check(new String(updated,oldMoov+4,4,"US-ASCII").equals("free"),"old moov must become same-size free");
        check(Arrays.equals(part(original,oldMdat),part(updated,oldMdat)),"mdat bytes/location must stay unchanged");
        int moov=find(updated,0,updated.length,"moov"),mvhd=child(updated,moov,"mvhd"),vp=track(updated,moov,"vide"),ap=track(updated,moov,"soun");
        check(moov==original.length,"replacement moov must append at old EOF");
        int mp=payload(updated,mvhd),version=updated[mp]&255; long scale=bytes(updated).getInt(mp+(version==0?12:20))&0xffffffffL;
        check(scale%rate==0&&scale%10000==0,"movie timescale must preserve exact original and PCM ticks");
        long logical=96001L*(scale/rate),video=videoDuration*(scale/10000);
        check(duration(updated,mvhd,false)==Math.max(logical,video),"movie duration must exclude audio padding");
        check(duration(updated,child(updated,ap,"tkhd"),true)==logical,"audio track duration must be logical PCM duration");
        check(duration(updated,child(updated,vp,"tkhd"),true)==video,"video track duration must retain its time");
        check(Arrays.equals(part(original,child(original,oldVideo,"mdia")),part(updated,child(updated,vp,"mdia"))),"video media boxes must remain byte-identical");
        int edts=child(updated,ap,"edts"),elst=child(updated,edts,"elst"),ep=payload(updated,elst);
        check((updated[ep]&255)==1&&bytes(updated).getInt(ep+4)==1,"gapless edit must be one version1 entry");
        check(bytes(updated).getLong(ep+8)==logical&&bytes(updated).getLong(ep+16)==2048,"edit must remove exact declared priming/padding");
        check(bytes(updated).getInt(ep+24)==65536,"edit playback rate must be1");
        int oldAudio=track(original,oldMoov,"soun"),oldMedia=child(original,oldAudio,"mdia"),newMedia=child(updated,ap,"mdia");
        check(Arrays.equals(part(original,child(original,oldMedia,"minf")),part(updated,child(updated,newMedia,"minf"))),"AAC sample/chunk tables must remain byte-identical");
        if (video>0xffffffffL) check(version==1&&(updated[payload(updated,child(updated,vp,"tkhd"))]&255)==1,"duration overflow must upgrade header version");
        byte[] before=updated; boolean rejected=false;
        try { MP4Gapless.finalizeAac(file,rate,96001,2048,96); } catch (IOException expected) { rejected=true; }
        check(rejected&&Arrays.equals(before,Files.readAllBytes(file.toPath())),"repeat finalization must reject without mutation");
    }
    private static void reject(File directory,String name,byte[] data,long logical,int packets) throws Exception {
        File file=new File(directory,name+".mp4"); Files.write(file.toPath(),data); boolean rejected=false;
        try { MP4Gapless.finalizeAac(file,48000,logical,2048,packets); } catch (IOException expected) { rejected=true; }
        check(rejected&&Arrays.equals(data,Files.readAllBytes(file.toPath())),name+" must reject without mutation");
    }
    public static void main(String[] args) throws Exception {
        File directory=Files.createTempDirectory("mp4-gapless-").toFile();
        try {
            success(directory,48000,20000,false); success(directory,44100,30000000,true);
            reject(directory,"count-mismatch",fixture(48000,96,1024,20000,false),96000,95);
            reject(directory,"invalid-AAC-clock",fixture(48000,96,960,20000,false),96000,96);
            reject(directory,"truncated-tail",fixture(48000,96,1024,20000,false),97000,96);
            byte[] zero=fixture(48000,96,1024,20000,false); bytes(zero).putInt(0,0); reject(directory,"zero-sized-box",zero,96000,96);
            System.out.println("PASS MP4Gapless structural checks="+checks);
        } finally { File[] files=directory.listFiles(); if (files!=null) for (File file:files) file.delete(); directory.delete(); }
    }
}
