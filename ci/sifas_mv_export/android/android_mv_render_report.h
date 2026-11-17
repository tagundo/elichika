#ifndef SIFAS_ANDROID_MV_RENDER_REPORT_H
#define SIFAS_ANDROID_MV_RENDER_REPORT_H
/* Included inside the original Unity-thread bindings namespace. Diagnostics
 * are optional, read-only, and never become an export precondition. */
static char amv_report_text[12*1024];
static size_t amv_report_used;
static unsigned amv_report_samples;
static bool amv_report_written;
struct AmvReportFailureGuard {
    char saved[sizeof(managed_failure)];
    AmvReportFailureGuard(){memcpy(saved,managed_failure,sizeof(saved));}
    ~AmvReportFailureGuard(){memcpy(managed_failure,saved,sizeof(saved));}
};
static void amv_report_add(const char *format,...) {
    const size_t limit=sizeof(amv_report_text)-384;
    if(amv_report_used>=limit-1)return;
    va_list args;va_start(args,format);
    int n=vsnprintf(amv_report_text+amv_report_used,limit-amv_report_used,format,args);va_end(args);
    if(n>0)amv_report_used+=(size_t)n<limit-amv_report_used?(size_t)n:limit-amv_report_used-1;
}
template<class T>static bool amv_report_field(void *object,const char *name,const char *type,T *out) {
    if(!object)return false;Field item{};
    if(!field(&item,e.object_get_class(object),name,type,sizeof(T)))return false;
    *out=load<T>(object,item.offset);return true;
}
static void *amv_report_ref(void *object,const char *name) {
    void *result=nullptr;amv_report_field(object,name,nullptr,&result);return result;
}
static int amv_report_bool(void *object,const char *name) {
    uint8_t result=0;return amv_report_field(object,name,"System.Boolean",&result)?(result?1:0):-1;
}
static int amv_report_int(void *object,const char *name) {
    int32_t result=-1;amv_report_field(object,name,"System.Int32",&result);return result;
}
struct AmvReportMethods {Method renderer_enabled,shared_material,material_color;};
static AmvReportMethods amv_report_methods;
static const char *amv_report_quality_name(int mode) {
    switch(mode){case 10:return "Max3d";case 20:return "High3d";case 30:return "Middle";
        case 40:return "Low";case 50:return "Low2d";default:return "Unknown";}
}
static void amv_report_quality() {
    static const char *flags[]={"FrameRate60Fps","BaseLight","StageAmbient",
        "StageAnimation","StageColoring","StageControl","StageOverlayEffect","StageFlashLight",
        "StageDisplay","StageAudience","StageEmissive","PostEffect","StageCubemap","MemberAmbient",
        "MemberRimLight","MemberSpotLightShaft","MemberSpotLightArea","MemberSwingBone","PropAmbient",
        "PropRimLight","SplitScreen"};
    int32_t mode=-1;uint8_t refresh=0;amv_report_field(quality,"<Quality>k__BackingField",nullptr,&mode);
    bool refresh_ok=amv_report_field(quality,"<RefreshRateMode>k__BackingField","System.Boolean",&refresh);
    amv_report_add("Quality=%s(%d) MovieLive=%d RenderingResolution=%d RefreshRateMode=%d\n",amv_report_quality_name(mode),mode,
        amv_report_bool(quality,"<MovieLive>k__BackingField"),amv_report_int(quality,"<RenderingResolution>k__BackingField"),refresh_ok?(refresh?1:0):-1);
    for(const char *flag:flags){char name[96];snprintf(name,sizeof(name),"<%s>k__BackingField",flag);
        amv_report_add(" %s=%d",flag,amv_report_bool(quality,name));}
    amv_report_add("\n");
}
static void amv_report_target(const char *name,void *target) {
    if(!target){amv_report_add(" %s=null",name);return;}
    int32_t width=-1,height=-1;uint8_t created=0;
    bool w=value(m.texture_width,target,&width),h=value(m.texture_height,target,&height);
    bool c=value(m.rt_created,target,&created);
    amv_report_add(" %s=%dx%d created=%d",name,w?width:-1,h?height:-1,c?(created?1:0):-1);
}
static void amv_report_postfx(void *core,unsigned index) {
    void *post=amv_report_ref(core,"postProcess"),*behaviour=amv_report_ref(post,"behaviour");
    void *profile=amv_report_ref(behaviour,"profile");if(!profile)profile=amv_report_ref(post,"profile");
    uint8_t enabled=0;bool readable=behaviour&&value(m.behaviour_enabled,behaviour,&enabled);
    amv_report_add("Core%u FX: component=%d initialized=%d behaviour=%d Enabled=%d profile=%d",
        index,amv_report_bool(post,"enablePostEffect"),amv_report_bool(post,"<IsInitialized>k__BackingField"),
        readable?(enabled?1:0):-1,amv_report_bool(behaviour,"Enabled"),profile?1:0);
    for(const char *name:{"bloom","depthOfField","flare"}){
        void *model=amv_report_ref(profile,name);amv_report_add(" %s=%d",name,amv_report_bool(model,"m_Enabled"));}
    amv_report_add("\n");
}
static void amv_report_cameras() {
    static const char *names[]={"beforePostprocessingBuffer","afterPostprocessingBuffer","depthBuffer","captureRenderTexture"};
    amv_report_add("Intermediate RTs:");
    for(const char *name:names)amv_report_target(name,amv_report_ref(camera_manager,name));
    amv_report_target("ownedFinal",rt);amv_report_add("\n");
    void *list=amv_report_ref(camera_manager,"cameras");uint32_t count=length(list,128);
    if(count==UINT32_MAX){amv_report_add("Current MV camera list unavailable\n");return;}
    amv_report_add("Current MV core cameras=%u\n",count);
    for(uint32_t i=0;i<count&&i<8;i++){
        void *core=element(list,i);amv_report_postfx(core,i);
        void *camera=reference(m.core_camera,core);Result target=invoke(m.camera_target,camera);
        int32_t width=-1,height=-1;value(m.camera_width,camera,&width);value(m.camera_height,camera,&height);
        amv_report_add(" Core%u viewport=%dx%d",i,width,height);
        if(target.ok)amv_report_target("targetTexture",target.value);else amv_report_add(" targetTexture=unavailable");
        amv_report_add("\n");
    }
    if(count>8)amv_report_add(" Additional camera details omitted after 8 owned cameras\n");
    Result target=invoke(m.camera_target,overlay_camera);amv_report_add("Final MV camera:");
    if(target.ok)amv_report_target("targetTexture",target.value);else amv_report_add(" targetTexture=unavailable");
    uint8_t compositor=0;bool state=session_overlay&&value(m.behaviour_enabled,session_overlay,&compositor);
    amv_report_add(" compositorEnabled=%d blur=%d\n",state?(compositor?1:0):-1,amv_report_bool(session_overlay,"isBlur"));
}
static void amv_report_shafts() {
    void *array=amv_report_ref(members,"members");uint32_t count=length(array,128);
    if(count==UINT32_MAX){amv_report_add("Current MV member list unavailable\n");return;}
    amv_report_add("Owned member shafts=%u (slot indices, no scene-wide search)\n",count);
    for(uint32_t i=0;i<count&&i<16;i++){
        void *member=element(array,i),*shaft=amv_report_ref(member,"spotLightShaft");
        if(!shaft){amv_report_add(" Slot%u shaft=absent\n",i);continue;}
        void *renderer=amv_report_ref(shaft,"lightShaftRenderer"),*material=amv_report_ref(shaft,"lightShaftMaterial");
        uint8_t enabled=0;bool state=renderer&&value(amv_report_methods.renderer_enabled,renderer,&enabled);
        Result shared=renderer?invoke(amv_report_methods.shared_material,renderer):Result{false,nullptr};
        float color[4]={};Field cached{};bool cached_ok=field(&cached,e.object_get_class(shaft),"cachedColor","UnityEngine.Color",sizeof(color));
        if(cached_ok)memcpy(color,(uint8_t *)shaft+cached.offset,sizeof(color));
        amv_report_add(" Slot%u paused=%d force=%d draw=%d cachedAlpha=",i,amv_report_bool(shaft,"paused"),
            amv_report_bool(shaft,"forceUpdate"),amv_report_int(shaft,"currentDrawIndex"));
        if(cached_ok)amv_report_add("%.6g",(double)color[3]);else amv_report_add("unavailable");
        amv_report_add(" rendererEnabled=%d sharedMaterialMatches=%d",state?(enabled?1:0):-1,shared.ok?(shared.value==material?1:0):-1);
        int32_t property=-1;bool property_ok=amv_report_field(shaft,"tintColorPropertyId","System.Int32",&property);
        struct Color {float r,g,b,a;} actual{};void *args[]={&property};
        if(material&&property_ok&&value(amv_report_methods.material_color,material,&actual,args))amv_report_add(" materialAlpha=%.6g",(double)actual.a);
        else amv_report_add(" materialAlpha=unavailable");
        amv_report_add("\n");
    }
    if(count>16)amv_report_add(" Additional member details omitted after 16 owned members\n");
}
static void amv_render_report_reset() {
    AmvReportFailureGuard preserve;amv_report_used=0;amv_report_samples=0;amv_report_written=false;amv_report_text[0]=0;
    amv_report_methods={};const char *ints[]={"System.Int32"};
    void *renderer=klass("UnityEngine","Renderer"),*material=klass("UnityEngine","Material");
    method(&amv_report_methods.renderer_enabled,renderer,"get_enabled",false,"System.Boolean",0,nullptr);
    method(&amv_report_methods.shared_material,renderer,"get_sharedMaterial",false,"UnityEngine.Material",0,nullptr);
    method(&amv_report_methods.material_color,material,"GetColor",false,"UnityEngine.Color",1,ints);
    amv_report_add("Elichika MV render diagnostics\nRequested=%ux%u fps=%u\nUnavailable values are -1 or unavailable.\n",config.width,config.height,config.fps);
    amv_report_add("Initial original MV before graph/target changes (no member scan):\n");amv_report_quality();amv_report_cameras();
    amv_report_add("A null camera.targetTexture may still use original SetTargetBuffers; inspect intermediate RT dimensions.\n");
}
static void amv_render_report_sample() {
    if(!have_tick||!simulation_hz)return;
    double seconds=(double)tick/simulation_hz;unsigned bit=0;
    if(!(amv_report_samples&1))bit=1;
    else if(seconds>=10&&!(amv_report_samples&2))bit=2;
    else if(seconds>=30&&!(amv_report_samples&4))bit=4;
    if(!bit)return;amv_report_samples|=bit;AmvReportFailureGuard preserve;
    amv_report_add("\nOutput sample at %.6f s; tick=%llu frame=%llu\n",seconds,(unsigned long long)tick,(unsigned long long)pending_frame);
    amv_report_quality();amv_report_cameras();amv_report_shafts();
}
static void amv_render_report_write(const char *path,bool restored) {
    if(amv_report_written)return;amv_report_written=true;
    if(!path||!path[0])return;char report_path[1200];int n=snprintf(report_path,sizeof(report_path),"%s.render-report.txt",path);
    if(n<0||(size_t)n>=sizeof(report_path))return;
    int tail=snprintf(amv_report_text+amv_report_used,sizeof(amv_report_text)-amv_report_used,
        "\nScene restoration=%s; output sample mask=%u\nRead-only diagnostics; no settings or render state were changed by this report.\nCustom mixer graph states were not sampled. These observations do not verify that every authored effect rendered.\n",
        restored?"completed":"failed",amv_report_samples);
    if(tail>0)amv_report_used+=(size_t)tail<sizeof(amv_report_text)-amv_report_used?(size_t)tail:sizeof(amv_report_text)-amv_report_used-1;
    FILE *file=fopen(report_path,"wb");if(!file)return;
    (void)fwrite(amv_report_text,1,amv_report_used,file);(void)fclose(file);
}
#endif
