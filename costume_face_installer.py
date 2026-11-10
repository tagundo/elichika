"""Receipt-backed installation of generated costume-local Face/Mouth ZIPs.

Only the app's canonical literal manifest and namespaced asset layout enter
this path. Arbitrary legacy addons keep their existing conservative installer.
The scene publisher supplies durable ownership, staging and complete rollback.
"""
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import uuid
import zipfile

import costume_scene_installer as shared


_NAME = re.compile(r"v[0-9a-f]{16}role[1-9][0-9]*\.(?:unity|png)\Z")


def _modules():
    shared._codec()  # source checkout and flattened native payload import path
    from webtools.core import viewer_archive, viewer_mod_package, viewer_mod_sources
    return viewer_archive, viewer_mod_package, viewer_mod_sources


def is_generated_face_package(path):
    """Dispatch only a canonical generated layout, without executing metadata."""
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("modinstall.txt")
            if info.file_size > 65536 or not any(_NAME.fullmatch(name) for name in archive.namelist()):
                return False
            _, package, _ = _modules()
            fields, _ = package._manifest(archive.read(info), "Face costume")
            references = [fields.get(key) for key in package._ASSET_REFS if fields.get(key)]
            return (set(fields) == set(package._SUPPORTED_CONFIG) and
                    any(fields.get(key) for key in ("costume_facedynamic_file", "costume_facedynamic_file_ios")) and
                    bool(references) and all(isinstance(value, str) and _NAME.fullmatch(value) for value in references))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return False


def read_package(path, expected_sha256=None):
    path = shared._safe_file(path)
    if not path.is_file() or not 0 < path.stat().st_size <= shared.MAX_ARCHIVE_BYTES:
        raise ValueError("Choose a completed generated Face/Mouth costume ZIP.")
    raw = path.read_bytes()
    digest = shared._sha(raw)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("The selected Face/Mouth costume package changed before installation.")
    archive_rules, package, sources = _modules()
    files, occupied = {}, set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= archive_rules.MAX_ENTRIES:
            raise ValueError("The generated costume ZIP has too many entries.")
        total = 0
        for info in infos:
            name = str(archive_rules._entry_path(info))
            total += info.file_size
            if name.casefold() in occupied or total > archive_rules.MAX_UNPACKED_BYTES:
                raise ValueError("The generated costume ZIP has duplicate or oversized entries.")
            occupied.add(name.casefold())
            if not info.is_dir():
                files[name] = archive.read(info)
        active = [name for name in files if name.lower().endswith((".txt", ".zip"))]
        if active != ["modinstall.txt"]:
            raise ValueError("The generated costume ZIP contains active companion code.")
    fields, _ = package._manifest(files["modinstall.txt"], "Face costume")
    if set(fields) != set(package._SUPPORTED_CONFIG):
        raise ValueError("The generated costume manifest is incomplete or unsupported.")
    owner = package._owner(fields["chara_id"])
    if fields["chara_id_append"] is not None:
        package._owner(fields["chara_id_append"])
    if fields["id_costume"] is not None or fields["id_trade_product"] is not None:
        raise ValueError("Generated Face/Mouth costumes allocate fresh installation IDs.")
    for key in package._NAMES:
        if not isinstance(fields[key], str) or len(fields[key]) > 200 or "\0" in fields[key]:
            raise ValueError("The generated costume name is invalid.")
    facts = {}
    for key in package._ASSET_REFS:
        value = fields[key]
        if not isinstance(value, str) or value and (not _NAME.fullmatch(value) or value not in files):
            raise ValueError("A generated costume asset reference is missing or invalid.")
        if value and key != "thumbnail_file":
            facts[key] = sources._model_facts(files[value])
            if facts[key]["platform"] not in ("android", "ios"):
                raise ValueError("A costume asset has no supported native platform.")
    if not fields["costume_file"] or not any(fields[key] for key in ("costume_facedynamic_file", "costume_facedynamic_file_ios")):
        raise ValueError("The generated costume needs its body and private face.")
    native = facts["costume_file"]["platform"]
    dual = bool(fields["costume_file_ios"])
    if dual and (native != "android" or facts["costume_file_ios"]["platform"] != "ios"):
        raise ValueError("The dual costume's native body roles are inconsistent.")
    if not dual and fields["costume_facedynamic_file_ios"]:
        raise ValueError("An iOS face suffix requires a dual-platform costume.")
    for key, row in facts.items():
        expected = "ios" if key.endswith("_ios") else native
        if row["platform"] != expected:
            raise ValueError("A costume companion uses the wrong native platform.")
        if "facedynamic" in key and row["owner"] not in (None, owner):
            raise ValueError("The private face belongs to a different character.")
    member = 423-owner if owner in (211, 212) else owner
    if member == 209:
        if not fields["rina_unmask_costume_file"] or dual and not fields["rina_unmask_costume_file_ios"]:
            raise ValueError("Rina's generated costume needs both native board/unmasked variants.")
    elif fields["rina_unmask_costume_file"] or fields["rina_unmask_costume_file_ios"]:
        raise ValueError("Only Rina costumes can declare an unmasked companion.")
    return {"raw": raw, "sha256": digest, "files": files, "fields": fields,
            "manifest": {"display_name": fields["costume_name_en"] or "Face/Mouth costume"},
            "member": member, "platforms": ("android", "ios") if dual else (native,)}


def prepare_package(decoded, root):
    root = Path(root).resolve()
    fields, files, member = decoded["fields"], decoded["files"], decoded["member"]
    plan = shared.ScenePlan(root, decoded)
    plan.updates = []
    plan.target_member_id = fields["chara_id_append"] or member
    for path in (root/".costume-management"/"receipts").glob("*.json"):
        shared._safe_file(path)
        if path.stat().st_size > 8*1024*1024:
            raise ValueError("An installation receipt is too large.")
        receipt = json.loads(path.read_text())
        if receipt.get("state") == "committed" and receipt.get("source", {}).get("package_sha256") == decoded["sha256"]:
            raise ValueError("This exact Face/Mouth costume ZIP is already installed. Save a new copy for an independent installation.")
    # Producer file names are not a trust boundary for Unity's runtime cache.
    # Rebase the complete body/face graph for this installation too, proving
    # every nonidentity byte unchanged. The preserved archive stays original.
    _, package, _ = _modules()
    with tempfile.TemporaryDirectory(prefix="elichika-face-install-") as temporary:
        temporary = Path(temporary)
        copy = temporary/"package.zip"
        copy.write_bytes(decoded["raw"])
        identity = package._isolate_face_graph(copy, temporary, lambda: False)
        with zipfile.ZipFile(copy) as archive:
            execution_files = {name: archive.read(name) for name in files}
    decoded = {**decoded, "files": execution_files, "execution_identity": identity, "execution_identity_rebased": True}
    files = decoded["files"]
    plan.decoded = decoded
    with closing(shared._connect(root/shared.MASTER_DBS[0], readonly=True)) as gl, closing(shared._connect(root/shared.MASTER_DBS[1], readonly=True)) as jp:
        plan.suit_id = shared._fresh_suit([gl, jp])
    key = "suit_name_" + str(plan.suit_id)
    # UUID paths are checked against every native catalog before publication.
    roles = {"C":"face"+uuid.uuid4().hex, "R":"face"+uuid.uuid4().hex,
             "F":"face"+uuid.uuid4().hex, "T":"face"+uuid.uuid4().hex}
    plan.main_model_path = roles["C"]
    defaults = shared._defaults()
    thumbnail = roles["T"] if fields["thumbnail_file"] else defaults["DEFAULT_THUMBNAILS"][member]
    for relative in shared.MASTER_DBS:
        with closing(shared._connect(root/relative, readonly=True)) as db:
            candidate = db.execute("SELECT id FROM m_suit WHERE member_m_id=? ORDER BY id LIMIT 1", (member,)).fetchone()
            if not candidate:
                raise ValueError("The costume's original character is missing from masterdata.")
            row = shared._row(db, "m_suit", "id=?", (candidate[0],))
            row.update(id=plan.suit_id, member_m_id=plan.target_member_id, name="k."+key,
                       thumbnail_image_asset_path=thumbnail, model_asset_path=roles["C"],
                       suit_release_route=2, suit_release_value=0, display_order=shared._display(db, plan.target_member_id))
            plan.add(relative,"m_suit",row)
            if member==209:
                plan.add(relative,"m_suit_view",dict(suit_master_id=plan.suit_id,view_status=2,model_asset_path=roles["R"]))
    for region,languages in shared.REGION_LANGUAGES.items():
        for language in languages:
            plan.add(f"assets/db/{region}/dictionary_{language}_k.db", "m_dictionary",
                     dict(id=key,message=fields["costume_name_"+language] or fields["costume_name_en"]))
    destination=shared._pack_destination(root)
    records={}
    for platform in decoded["platforms"]:
        suffix="_ios" if platform=="ios" and len(decoded["platforms"])==2 else ""
        refs={"C":"costume_file"+suffix, "R":"rina_unmask_costume_file"+suffix,
              "F":"costume_facedynamic_file"+suffix, "T":"thumbnail_file"}
        records[platform]={}
        for role,field in refs.items():
            if not fields[field]:
                continue
            raw=files[fields[field]]
            pack,encoded=shared._pack(raw,plan.install_key+":"+platform+":"+role)
            plan.files[platform+":"+role]=dict(path=destination/pack,data=encoded,sha256=shared._sha(encoded),size=len(encoded))
            records[platform][role]=(pack,len(encoded))
        for region,languages in shared.REGION_LANGUAGES.items():
            for language in languages:
                relative=f"assets/db/{region}/asset_{shared.PLATFORM_CODES[platform]}_{language}.db"
                with closing(shared._connect(root/relative,readonly=True)) as db:
                    for role,path in roles.items():
                        table="texture" if role=="T" else "member_model"
                        if db.execute('SELECT 1 FROM "'+table+'" WHERE asset_path=?',(path,)).fetchone():
                            raise ValueError("A private costume path collided with an existing asset.")
                    for role,(pack,size) in records[platform].items():
                        plan.add(relative,"m_asset_pack",dict(pack_name=pack,auto_delete=0))
                        plan.add(relative,"texture" if role=="T" else "member_model",
                                 dict(asset_path=roles[role],pack_name=pack,head=0,size=size,key1=0,key2=0))
                    edges=set()
                    for kind,target,value in defaults["DEPENDENCIES"][member]:
                        dependency=roles["F"] if kind=="face_or" and "F" in records[platform] else value
                        if dependency != roles["F"]:
                            shared._descriptor(db,dependency)
                        elif kind=="face_or":
                            # Stock faces currently use their body's flat
                            # dependency list. Preserve any explicit shared
                            # face dependencies in extended catalogs too;
                            # those pre-existing rows/files are never owned.
                            extra=[row[0] for row in db.execute(
                                "SELECT dependency FROM member_model_dependency WHERE asset_path=?",(value,))]
                            if extra:
                                shared._closure(db,[value])
                                edges.update((roles["F"],item) for item in extra)
                        edges.add((roles[target],dependency))
                    if "F" in records[platform]:
                        from costume_clone_assets import _bundle_metadata
                        face_cabs,face_names,_,_=_bundle_metadata(files[fields[refs["F"]]])
                        face_cabs={cab.lower() for cab in face_cabs}
                        face_names={name for _,name in face_names}
                        for target in ("C","R"):
                            if target in records[platform]:
                                _,_,externals,dependencies=_bundle_metadata(files[fields[refs[target]]])
                                if (any(cab in external.lower() for cab in face_cabs for external in externals)
                                        or face_names.intersection(dependencies)):
                                    edges.add((roles[target],roles["F"]))
                    for asset_path,dependency in sorted(edges):
                        plan.add(relative,"member_model_dependency",dict(asset_path=asset_path,dependency=dependency))
                    mappings=set()
                    for role,(pack,size) in records[platform].items():
                        package_key="main" if role=="T" else "suit:"+str(plan.suit_id)
                        plan.add(relative,"m_asset_package_mapping",dict(package_key=package_key,pack_name=pack,
                                 file_size=size,metapack_name=None,metapack_offset=0,category=8 if role=="T" else 3))
                        if role!="T":
                            mappings.add(pack)
                    # Eye/mouth animation packs are suit downloads, not always
                    # part of main. A fresh client needs this complete shared
                    # dependency closure even without the original costume's
                    # cached packs. Only new mappings are owned, never the
                    # pre-existing descriptors, packs or shared file bytes.
                    shared_roots={dependency for _,dependency in edges if dependency not in roles.values()}
                    for pack in sorted(shared._closure(db,shared_roots)):
                        if pack not in mappings:
                            row=shared._mapping(db,pack)
                            row.update(package_key="suit:"+str(plan.suit_id))
                            plan.add(relative,"m_asset_package_mapping",row)
                            mappings.add(pack)
                    plan.add(relative,"m_asset_package",dict(package_key="suit:"+str(plan.suit_id),
                             version=hashlib.sha1(uuid.uuid4().bytes).hexdigest(),pack_num=len(mappings)))
                    if "T" in records[platform]:
                        if db.execute("SELECT COUNT(*) FROM m_asset_package WHERE package_key='main'").fetchone()[0]!=1:
                            raise ValueError("The main download package is missing or ambiguous.")
                        plan.shared_updates.append(relative)
    user=root/"userdata.db"
    if user.is_file():
        with closing(shared._connect(user,readonly=True)) as db:
            for (user_id,) in db.execute("SELECT user_id FROM u_status"):
                plan.add("userdata.db","u_suit",dict(user_id=user_id,suit_master_id=plan.suit_id,is_new=0))
            if "u_member" in {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                columns=shared._columns(db,"u_member")
                for row in db.execute("SELECT * FROM u_member WHERE member_master_id=?",(member,)):
                    before=dict(zip(columns,row))
                    plan.updates.append(dict(db="userdata.db",table="u_member",before=before,after={"suit_master_id":plan.suit_id}))
    archive=root/".costume-management"/"sources"/(plan.install_key+".zip")
    plan.files["source_archive"]=dict(path=archive,data=decoded["raw"],sha256=decoded["sha256"],size=len(decoded["raw"]))
    for value in plan.files.values():
        if shared._safe_file(value["path"]).exists():
            raise ValueError("A managed costume output already exists; nothing was replaced.")
    plan.model_paths={"primary":roles["C"],"face":roles["F"],**({"unmasked":roles["R"]} if member==209 else {})}
    return plan


def install_package(path, expected_sha256=None, *, root=".", do_backup=True, log=print, should_stop=lambda: False):
    from database_maintenance import guard
    root=Path(root).resolve()
    with guard(root):
        if should_stop():
            raise InterruptedError("Costume installation was cancelled.")
        decoded=read_package(path,expected_sha256)
        plan=prepare_package(decoded,root)
        return shared.publish_plan(plan,path,decoded["sha256"],do_backup=do_backup,log=log,
            kind="costume",label=decoded["manifest"]["display_name"],should_stop=should_stop,
            source_metadata={"generated_private_face":True,"native_platforms":list(decoded["platforms"]),
                             "private_model_paths":plan.model_paths,
                             "execution_identity":plan.decoded["execution_identity"]})
