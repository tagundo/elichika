#include "../native/MVPixelConvert.hpp"
#include <cassert>
#include <cstdint>
#include <vector>
#include <cstring>
#include <limits>
int main(){
 for(uint32_t width:{1u,2u,7u,15u,16u,17u,31u,32u,33u,3840u})for(uint32_t height:{1u,2u,5u})for(size_t padding:{size_t(0),size_t(13)}){
  size_t packed=size_t(width)*4,stride=packed+padding;
  std::vector<uint8_t> source(packed*height),output(stride*height,37),expected(output);
  for(size_t i=0;i<source.size();i++)source[i]=uint8_t(i*73+19);
  for(uint32_t y=0;y<height;y++)for(uint32_t x=0;x<width;x++){
   const auto *p=source.data()+size_t(height-1-y)*packed+size_t(x)*4;auto *q=expected.data()+size_t(y)*stride+size_t(x)*4;
   q[0]=p[2];q[1]=p[1];q[2]=p[0];q[3]=255;
  }
  assert(elichika::rgbaToOpaqueBGRA(source.data(),source.size(),width,height,output.data(),output.size(),stride));
  assert(output==expected);
 }
 uint8_t data[64]={},out[64]={};
 assert(!elichika::rgbaToOpaqueBGRA(nullptr,64,2,2,out,64,8));
 assert(!elichika::rgbaToOpaqueBGRA(data,64,0,2,out,64,8));
 assert(!elichika::rgbaToOpaqueBGRA(data,15,2,2,out,64,8));
 assert(!elichika::rgbaToOpaqueBGRA(data,64,2,2,out,15,8));
 assert(!elichika::rgbaToOpaqueBGRA(data,64,2,2,out,64,7));
 assert(!elichika::rgbaToOpaqueBGRA(data,64,2,2,data,64,8));
 assert(!elichika::rgbaToOpaqueBGRA(data,64,2,2,data+3,61,8));
 assert(!elichika::rgbaToOpaqueBGRA(data,64,2,2,out,64,std::numeric_limits<size_t>::max()));
}
