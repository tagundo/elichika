"""Exercise the actual backend lifecycle helpers across deferred native Destroy."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
HEADER = ROOT / 'ci/sifas_mv_export/android'
BACKENDS = ('ci/sifas_mv_export/android/android_mv_game_bindings.cpp',
            'ios/native/SIFASMVExportBindings.mm')


def function(text, name):
    start = text.index('bool ' + name + '() {')
    first = text.index('{', start)
    depth = 1
    pos = first + 1
    while depth:
        depth += (text[pos] == '{') - (text[pos] == '}')
        pos += 1
    return text[start:pos]


HARNESS = r'''
#include "mv_particle_culling.h"
#include <cassert>
#include <cstdio>
#include <cstdarg>
#include <cstring>
struct ParticleSnapshot {void *object;uint32_t handle;sifas_mv_particles::Policy policy;};
ParticleSnapshot particle_snapshots[8];uint32_t particle_count,particle_scene_count;
struct {struct {size_t offset;}particle_native;}f={{0x10}};
struct {void *targets[8];void *gchandle_get_target(uint32_t h){return h?targets[h]:nullptr;}}e;
void *dead_object;void *poison_object;bool is_live[8];unsigned releases;
char diagnostic[160];
bool alive(void *p){if(!p||p==dead_object)return false;for(unsigned i=1;i<8;i++)if(e.targets[i]==p)return is_live[i];return false;}
void release(uint32_t *h){if(*h){e.targets[*h]=nullptr;is_live[*h]=false;++releases;}*h=0;}
bool setup_rejected(const char *fmt,...){va_list a;va_start(a,fmt);vsnprintf(diagnostic,sizeof(diagnostic),fmt,a);va_end(a);return false;}
template<class T>T load(void *p,size_t off){assert(p!=poison_object);return sifas_mv_particles::read<T>(p,off);}
FUNCTIONS
struct Fixture {
 alignas(8) unsigned char managed[32],native[128],parameters[128],state[128];
 Fixture(){std::memset(this,0,sizeof(*this));sifas_mv_particles::write<void *>(managed,0x10,native);sifas_mv_particles::write<void *>(native,0x40,parameters);sifas_mv_particles::write<void *>(native,0x48,state);sifas_mv_particles::write<int32_t>(parameters,0x40,1);}
 void bind(unsigned index){auto &s=particle_snapshots[index];s.object=managed;s.handle=index+1;e.targets[index+1]=managed;is_live[index+1]=true;assert(sifas_mv_particles::snapshot(s.policy,native));sifas_mv_particles::apply(s.policy,[](void*){});}
};
int main(){
 Fixture old_clone,current;
 particle_count=2;old_clone.bind(0);current.bind(1);
 assert(particle_owners_valid());assert(releases==0);
 // Unity's end-of-frame Destroy retires the old graph clone. Any attempt to
 // inspect its cached native address now would be invalid.
 dead_object=poison_object=old_clone.managed;
 sifas_mv_particles::write<void *>(old_clone.managed,0x10,reinterpret_cast<void *>(1));
 assert(particle_owners_valid());assert(!particle_snapshots[0].handle&&releases==1);
 assert(particle_owners_valid());assert(releases==1);
 assert(restore_particle_culling());assert(!particle_count&&releases==2);
 assert(sifas_mv_particles::read<int32_t>(current.parameters,0x40)==1);
 // Every kind of change to a still-live owner remains an error.
 Fixture changed;particle_count=1;changed.bind(0);
 void *owner=e.targets[1];e.targets[1]=nullptr;assert(!particle_owners_valid());assert(std::strstr(diagnostic,"managed owner"));e.targets[1]=owner;
 sifas_mv_particles::write<void *>(changed.managed,0x10,current.native);assert(!particle_owners_valid());assert(std::strstr(diagnostic,"native owner"));sifas_mv_particles::write<void *>(changed.managed,0x10,changed.native);
 sifas_mv_particles::write<void *>(changed.native,0x40,current.parameters);assert(!particle_owners_valid());assert(std::strstr(diagnostic,"parameter block"));sifas_mv_particles::write<void *>(changed.native,0x40,changed.parameters);
 sifas_mv_particles::write<void *>(changed.native,0x48,current.state);assert(!particle_owners_valid());assert(std::strstr(diagnostic,"simulation state"));sifas_mv_particles::write<void *>(changed.native,0x48,changed.state);
 sifas_mv_particles::write<int32_t>(changed.parameters,0x40,2);assert(!particle_owners_valid());assert(std::strstr(diagnostic,"culling policy"));sifas_mv_particles::write<int32_t>(changed.parameters,0x40,3);
 assert(particle_owners_valid());assert(restore_particle_culling());
 puts("PASS deferred Destroy before capture zero; no stale native access; live owner/parameter/state/policy guards retained; cleanup restores live policy");
}
'''


class DeferredParticleDestroy(unittest.TestCase):
    def test_actual_backend_helpers(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as work:
                text = (ROOT / backend).read_text()
                helpers = '\n'.join(function(text, n) for n in
                                    ('particle_owners_valid', 'restore_particle_culling'))
                source = Path(work) / 'check.cpp'
                source.write_text(HARNESS.replace('FUNCTIONS', helpers))
                binary = Path(work) / 'check'
                subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++11', '-Wall',
                                '-Wextra', '-Werror', '-pedantic', '-I', str(HEADER),
                                str(source), '-o', str(binary)], check=True)
                subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
