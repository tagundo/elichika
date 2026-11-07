# Renamed MV root observation: source review

This isolated QA branch starts at `7d278186a9c16a3cafed23265f0f81780fc96ac3`.
It changes no product, installer, model fixture, UI reader, input command, or
APK. It has not been dispatched. Local policy/auditor tests establish their
own rejection behavior, not a native scene result.

The original GL3.12 static `LiveMemberPrefabSpawner.Spawn(member, prefab,
usePrefab)` clones under the typed member Transform and renames its returned
GameObject to `Model`. Its sole direct caller supplies the original prefab and
`usePrefab=false`. The old observer recognizes only the original two Rina
names, including their ordinary `(Clone)` suffix; it cannot identify that
renamed MV root. Run `42350210082` finished three normal MVs and returned to
HOME with clean observer teardown, but its MV Node/Swing coverage remains
incomplete. That is a coverage limit, not evidence of a scaling failure.

The added listener observes that exact static Spawn overload at `0x2926bd8`.
It accepts only the original board/bare Rina prefab names and a typed
`LiveCoreMember` owner, with `usePrefab=false`. After return it independently
reads the actual `Model` name, root GameObject and Transform IDs, and the typed
owner and current parent through the retained `GetComponentInParent(Type)`
API. All six object IDs must be distinct. The map retains numeric/string
provenance only, at most 32 bindings and 256 owner generations. Every observed
typed-owner spawn evicts the old owner binding before prefab reads; every
typed returned root evicts an old root binding even when its frame is rejected.
Rejected context never permits Unity object reads. A read failure is a failed
observer, not evidence that a model was absent.

Root lookup, each accepted Model enter/leave sample, and delayed snapshots
revalidate the current name, owner, parent and numeric identity. The actual
public root name stays `Model`; its original prefab identity is recorded in a
separate `spawnBinding` object. There is no global name hook, generic Model
allowlist, native mutation, retained component cache, or registry bootstrap.
Only the existing original Node.Initialize completion registers a scaler.

The auditor requires the exact ready ABI policy and a prior verified Spawn
event with the same Transform ID and complete typed provenance. An explicit
invalidation removes that evidence. Event sequence numbers and snapshot event
cutoffs disambiguate events that share a wall-clock millisecond. GameObject
and Transform IDs, booleans and integers cannot substitute for one another.
Delayed Model samples also join their original Node.Initialize, ApplyScale
and Swing evidence by the exact same binding generation. Reuse of a scaler
and root ID after a valid respawn cannot reuse old initialization evidence;
a same-millisecond Initialize beyond the snapshot event cutoff is excluded.
The original six Node/Swing/marker hooks, invocation counter, desired values,
physics comparisons and numeric tolerances remain unchanged.

`fixtures/spawn-binding-abi.json` records 16 exact retained method signatures
and ARM64 addresses from the pinned original metadata/ELF. It includes the
static Spawn argument indices and the retained owner-lookup API. Static
availability does not prove actual callback order. A future separately
approved scene run must still observe valid Spawn-before-Model provenance,
original Node/Swing initialization, delayed values, normal routes and fresh UI
before the strict scene auditor can pass. Main, PR 68 and release APKs are
unchanged by this branch.

The exact owner-type guard stays in place. `LiveCoreMember` is not sealed, but
the pinned metadata's complete 18,996-type parent scan finds no direct subclass
in ordinary or generic-parent forms, hence no indirect subclass. This supports
the guard for this unchanged client; a different runtime type still refuses
observation and is not silently broadened.

Source-only checks:

```sh
node --check tests/rina_scene_qa/scene_observer.js
node --check tests/rina_scene_qa/spawn_bindings.js
python -m unittest discover -s tests/rina_scene_qa -p 'test_spawn*.py' -v
```
