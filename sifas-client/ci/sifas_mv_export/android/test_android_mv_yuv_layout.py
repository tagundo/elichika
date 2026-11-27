"""Run the actual Java plane writer against host Image fixtures and its old loop.

This verifies buffer layout/copy behavior, not a device codec or export speed.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).with_name('AndroidMVEncoder.java')


def writer_method(text):
    start = text.index('    private static void writeI420(')
    brace = text.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


HARNESS = r'''
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.Random;

public final class YuvLayoutCheck {
    static final class ImageFormat { static final int YUV_420_888=35; }
    static final class Rect {
        int left,top,right,bottom;
        Rect(int w,int h) { right=w; bottom=h; }
        int width() { return right-left; }
        int height() { return bottom-top; }
    }
    static final class Image {
        static final class Plane {
            final ByteBuffer buffer;
            int row,pixel;
            Plane(ByteBuffer b,int r,int p) { buffer=b; row=r; pixel=p; }
            ByteBuffer getBuffer() { return buffer; }
            int getRowStride() { return row; }
            int getPixelStride() { return pixel; }
        }
        int format=ImageFormat.YUV_420_888,width,height;
        final Rect crop;
        final Plane[] planes;
        Image(int w,int h,Plane[] p) { width=w; height=h; crop=new Rect(w,h); planes=p; }
        int getFormat() { return format; }
        int getWidth() { return width; }
        int getHeight() { return height; }
        Rect getCropRect() { return crop; }
        Plane[] getPlanes() { return planes; }
    }
    static final class Layout {
        final Image image;
        final ByteBuffer[] memory;
        Layout(Image i,ByteBuffer... m) { image=i; memory=m; }
    }

ACTUAL_METHOD

    // Frozen original writer, independent of the optimized method above.
    private static void original(Image image,byte[] source,int width,int height) throws IOException {
        if (image.getFormat()!=ImageFormat.YUV_420_888 || image.getWidth()<width || image.getHeight()<height
                || image.getPlanes().length!=3 || image.getCropRect().left!=0 || image.getCropRect().top!=0
                || image.getCropRect().width()!=width || image.getCropRect().height()!=height)
            throw new IOException("Unexpected flexible YUV layout");
        int offset=0;
        for (int p=0;p<3;p++) {
            int w=p==0?width:width/2, h=p==0?height:height/2;
            Image.Plane plane=image.getPlanes()[p];
            ByteBuffer target=plane.getBuffer().duplicate();
            int base=target.position(), row=plane.getRowStride(), pixel=plane.getPixelStride();
            long last=(long)base+(long)(h-1)*row+(long)(w-1)*pixel;
            if (row<=0 || pixel<=0 || last>=target.limit()) throw new IOException("Invalid YUV plane strides");
            for (int y=0;y<h;y++) for (int x=0;x<w;x++)
                target.put(base+y*row+x*pixel,source[offset++]);
        }
    }
    static ByteBuffer memory(int capacity,boolean direct) {
        ByteBuffer b=direct?ByteBuffer.allocateDirect(capacity):ByteBuffer.allocate(capacity);
        for (int n=0;n<capacity;n++) b.put(n,(byte)0x6d);
        return b;
    }
    static Image.Plane plane(ByteBuffer memory,int base,int limit,int row,int pixel) {
        ByteBuffer view=memory.duplicate();
        view.limit(limit); view.position(base); view.mark();
        return new Image.Plane(view,row,pixel);
    }
    static Layout planar(int width,int height,int yrow,int crow,int base,boolean shortLast,boolean direct) {
        Image.Plane[] planes=new Image.Plane[3];
        ByteBuffer[] blocks=new ByteBuffer[3];
        for (int p=0;p<3;p++) {
            int w=p==0?width:width/2,h=p==0?height:height/2;
            int row=p==0?yrow:crow,start=base+p;
            int end=start+(h-1)*row+w;
            blocks[p]=memory(shortLast?end:end+row+7,direct);
            planes[p]=plane(blocks[p],start,shortLast?end:blocks[p].capacity()-3,row,1);
        }
        return new Layout(new Image(width,height,planes),blocks);
    }
    static Layout sharedUV(int width,int height,boolean vu,boolean direct) {
        int cw=width/2,ch=height/2,ybase=3,uvbase=5,yrow=width+7,uvrow=2*cw+6;
        int ubase=uvbase+(vu?1:0),vbase=uvbase+(vu?0:1);
        int yend=ybase+(height-1)*yrow+width;
        int uend=ubase+(ch-1)*uvrow+(cw-1)*2+1;
        int vend=vbase+(ch-1)*uvrow+(cw-1)*2+1;
        ByteBuffer y=memory(yend,direct),uv=memory(Math.max(uend,vend),direct);
        Image.Plane[] p={plane(y,ybase,yend,yrow,1),plane(uv,ubase,uend,uvrow,2),
                         plane(uv,vbase,vend,uvrow,2)};
        return new Layout(new Image(width,height,p),y,uv);
    }
    static Layout mixed(boolean direct) {
        ByteBuffer y=memory(101,direct),u=memory(63,direct),v=memory(57,direct);
        Image.Plane[] p={plane(y,5,92,17,1),plane(u,7,59,19,3),plane(v,3,51,17,2)};
        return new Layout(new Image(8,4,p),y,u,v);
    }
    static byte[] snapshot(ByteBuffer b) {
        ByteBuffer view=b.duplicate(); view.clear();
        byte[] bytes=new byte[view.remaining()]; view.get(bytes); return bytes;
    }
    static void check(boolean ok,String detail) {
        if (!ok) throw new AssertionError(detail);
    }
    static String invoke(Layout layout,byte[] source,int width,int height,boolean old) {
        try {
            if (old) original(layout.image,source,width,height);
            else writeI420(layout.image,source,width,height);
            return "OK";
        } catch (Exception error) { return error.getClass().getName()+":"+error.getMessage(); }
    }
    static int cases;
    static void compare(String label,Layout actual,Layout expected,int width,int height,boolean valid) {
        byte[] source=new byte[width*height*3/2+31];
        for (int n=0;n<source.length;n++) source[n]=(byte)(n*73+(n>>>4)*19+11);
        byte[] sourceBefore=source.clone();
        int[] positions=new int[3],limits=new int[3];
        for (int p=0;p<3;p++) {
            positions[p]=actual.image.planes[p].buffer.position();
            limits[p]=actual.image.planes[p].buffer.limit();
        }
        String got=invoke(actual,source,width,height,false);
        String want=invoke(expected,source,width,height,true);
        check(got.equals(want),label+" exception differs: "+got+" / "+want);
        check(valid?got.equals("OK"):!got.equals("OK"),label+" unexpected acceptance: "+got);
        check(Arrays.equals(source,sourceBefore),label+" modified source");
        for (int b=0;b<actual.memory.length;b++)
            check(Arrays.equals(snapshot(actual.memory[b]),snapshot(expected.memory[b])),label+" backing bytes "+b);
        int offset=0;
        for (int p=0;p<3;p++) {
            Image.Plane plane=actual.image.planes[p];
            check(plane.buffer.position()==positions[p]&&plane.buffer.limit()==limits[p],label+" changed position/limit");
            plane.buffer.reset();
            check(plane.buffer.position()==positions[p],label+" changed mark");
            int w=p==0?width:width/2,h=p==0?height:height/2;
            if (valid && plane.row>=w*plane.pixel) {
                for (int y=0;y<h;y++) for (int x=0;x<w;x++)
                    check(plane.buffer.get(positions[p]+y*plane.row+x*plane.pixel)==source[offset+y*w+x],
                          label+" incorrect source offset in plane "+p);
            }
            offset+=w*h;
        }
        cases++;
    }
    public static void main(String[] args) {
        for (boolean direct:new boolean[]{false,true}) {
            compare("tight",planar(8,6,8,4,0,true,direct),planar(8,6,8,4,0,true,direct),8,6,true);
            compare("padding/position",planar(8,6,13,9,5,false,direct),planar(8,6,13,9,5,false,direct),8,6,true);
            compare("short final capacity",planar(8,6,13,9,5,true,direct),planar(8,6,13,9,5,true,direct),8,6,true);
            compare("shared UV",sharedUV(8,6,false,direct),sharedUV(8,6,false,direct),8,6,true);
            compare("shared VU",sharedUV(8,6,true,direct),sharedUV(8,6,true,direct),8,6,true);
            compare("mixed pixel strides",mixed(direct),mixed(direct),8,4,true);
            compare("legacy overlapping rows",planar(8,6,5,3,2,true,direct),planar(8,6,5,3,2,true,direct),8,6,true);
            for (int failure=0;failure<8;failure++) {
                Layout a=planar(8,6,13,9,5,true,direct),b=planar(8,6,13,9,5,true,direct);
                for (Layout l:new Layout[]{a,b}) {
                    if (failure==0) l.image.planes[0].row=0;
                    if (failure==1) l.image.planes[1].pixel=0;
                    if (failure==2) l.image.planes[2].buffer.limit(l.image.planes[2].buffer.limit()-1);
                    if (failure==3) l.image.planes[1].row=-1;
                    if (failure==4) l.image.format=0;
                    if (failure==5) l.image.crop.left=1;
                    if (failure==6) l.image.width=7;
                    if (failure==7) l.image.planes[0].pixel=-1;
                }
                compare("invalid "+failure,a,b,8,6,false);
            }
        }
        Random random=new Random(187);
        for (int n=0;n<240;n++) {
            int w=2*(1+random.nextInt(12)),h=2*(1+random.nextInt(10));
            int yrow=w+random.nextInt(12),crow=w/2+random.nextInt(9),base=random.nextInt(9);
            boolean shortLast=random.nextBoolean(),direct=random.nextBoolean();
            compare("random "+n,planar(w,h,yrow,crow,base,shortLast,direct),
                    planar(w,h,yrow,crow,base,shortLast,direct),w,h,true);
        }
        System.out.println("PASS "+cases+" layouts: byte-identical original loop, visible source offsets, padding, positions/limits/marks, short final rows, shared UV, stride rejection");
    }
}
'''


class YuvPlaneWriter(unittest.TestCase):
    def test_actual_java_method_matches_original(self):
        java = os.environ.get('JAVA', 'java')
        with tempfile.TemporaryDirectory(prefix='mv-yuv-layout-') as work:
            source = Path(work) / 'YuvLayoutCheck.java'
            source.write_text(HARNESS.replace('ACTUAL_METHOD', writer_method(SOURCE.read_text())))
            subprocess.run([java, '--module', 'jdk.compiler/com.sun.tools.javac.Main',
                            '-source', '8', '-target', '8', '-Xlint:-options',
                            '-d', work, str(source)], check=True, timeout=60)
            subprocess.run([java, '-cp', work, 'YuvLayoutCheck'], check=True, timeout=60)


if __name__ == '__main__':
    unittest.main()
