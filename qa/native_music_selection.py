"""Pure qualification of a prospective native music hit; never input authority."""
import math

DOWNLOAD_SONG_PATH='EntryPoint/Canvas/SafeArea/RightArea/Info/ButtonContainer/DecideButtonGameObjectSwitcher/DecideBtn/DownloadLabel'


def _number(value):return type(value) in (int,float) and math.isfinite(value)


def _contains(cell,point):
    bounds=cell.get('nativeBounds') or {};low=bounds.get('min') or {};high=bounds.get('max') or {}
    return all(_number(point.get(axis)) and _number(low.get(axis)) and _number(high.get(axis)) and
               low[axis]<=point[axis]<=high[axis] for axis in ('x','y','z'))


def native_music_hit_blocker(picked,requested):
    hit=picked.get('nativeMusicHit') or {}
    if hit.get('qualified') is not True:return 'Native music hit unavailable: '+str(hit.get('reason') or 'no qualified native witness')
    catalog=picked.get('catalog') or {}
    if catalog.get('liveMasterId')!=requested or catalog.get('isPlayable') is not True:
        return 'Native music current typed catalog VO differs from requested playable song'
    if catalog.get('active') is not True or not all(type(catalog.get(key)) is str and catalog[key]
        for key in ('id','gameObjectId','voId')):
        return 'Native music current typed component/GameObject/VO identity is unavailable'
    enumeration=hit.get('typedRowsEnumeration') or {}
    if (enumeration.get('complete') is not True or enumeration.get('error') or
        not all(type(enumeration.get(key)) is int for key in ('activeObjects','totalObjects','limit')) or
        not 1<=enumeration['activeObjects']<=enumeration['totalObjects']<=enumeration['limit']<=512):
        return 'Native music current typed-row enumeration is incomplete or unbounded'
    if hit.get('scope')!='PROSPECTIVE_NATIVE_HIT_PREDICTION':return 'Native music prospective witness scope is unavailable'
    if hit.get('intendedLiveMasterId')!=requested:return 'Native music intended VO differs from requested song'
    owners=hit.get('ownership') or {};camera=owners.get('eventCamera') or {}
    if not all(type(owners.get(key)) is str and owners[key] for key in
               ('viewId','modelId','inputProxyId','transitionId','dragOwnerId','dragRectId','raycasterId')):
        return 'Native music ownership or drag plane is unresolved'
    if (picked.get('target') or {}).get('id')!=owners['inputProxyId']:
        return 'Native music input target is not the currently owned input proxy'
    plane=hit.get('dragPlane') or {}
    if plane.get('rectId')!=owners['dragRectId'] or not all(
        _number((plane.get(name) or {}).get(axis)) for name,axes in (
            ('position','xyz'),('rotation','xyzw'),('pivot','xy'),('size','xy'),('lossyScale','xyz')) for axis in axes):
        return 'Native music current drag-handler plane geometry is unresolved'
    if camera.get('resolved') is not True or type(camera.get('isNull')) is not bool or camera.get('error'):
        return 'Native music current raycaster event camera is unresolved'
    if (camera['isNull'] and camera.get('id') is not None) or (not camera['isNull'] and not camera.get('id')):
        return 'Native music resolved event camera identity is inconsistent'
    cells=hit.get('orderedCells');point=hit.get('worldPoint') or {};intended=hit.get('intended') or {}
    if type(cells) is not list or not 0<len(cells)<=512 or hit.get('cellsComplete') is not True:
        return 'Native music ordered managed-cell enumeration is incomplete'
    if type(hit.get('listSignature')) is not str or not hit['listSignature']:
        return 'Native music ordered native-bounds signature is unavailable'
    if any(type(c) is not dict or type(c.get('ordinal')) is not int or c['ordinal']!=i for i,c in enumerate(cells)):
        return 'Native music managed-cell order is unproved'
    if any(not all(_number((c.get('nativeBounds') or {}).get(side,{}).get(axis))
                       for side in ('min','max') for axis in ('x','y','z')) for c in cells):
        return 'Native music ordered cell bounds are unreadable; first-hit prediction is incomplete'
    associated=[cell for cell in cells if cell.get('typedRowId')==catalog['id'] and
                cell.get('rectGameObjectId')==catalog['gameObjectId'] and cell.get('typedVOId')==catalog['voId']]
    if len(associated)!=1:return 'Native music intended typed-row/GameObject/VO association is absent or ambiguous'
    if (associated[0].get('associationQualified') is not True or associated[0].get('isPlayable') is not True):
        return 'Native music intended actual typed VO association is unqualified'
    first=next((cell for cell in cells if _contains(cell,point)),None)
    if first is None:return 'Native music world press point has no containing managed cell'
    if first.get('activeInHierarchy') is not True:return 'Native music FIRST containing cell is inactive; native fallback applies'
    identity=('ordinal','index','positionIndex','rectId','rectGameObjectId','typedRowId','typedVOId','liveMasterId')
    if any(first.get(key)!=intended.get(key) for key in identity) or first.get('liveMasterId')!=requested:
        return 'Native music FIRST containing cell differs from intended active VO'
    if (any(intended.get(key)!=associated[0].get(key) for key in identity) or
        intended.get('typedRowId')!=catalog['id'] or intended.get('rectGameObjectId')!=catalog['gameObjectId'] or
        intended.get('typedVOId')!=catalog['voId']):
        return 'Native music intended/native FIRST typed component or GameObject differs from current catalog'
    if any((hit.get('firstContaining') or {}).get(key)!=first.get(key) for key in identity):
        return 'Native music reported first hit differs from ordered native bounds'
    if type(first.get('index')) is not int or type(first.get('positionIndex')) is not int or not first.get('rectId'):
        return 'Native music cell index/position/RectTransform identity is unavailable'
    screen=hit.get('screenPoint') or {};center=(picked.get('target') or {}).get('center') or {}
    if not all(_number(screen.get(axis)) and screen[axis]==center.get(axis) for axis in ('x','y')):
        return 'Native music prospective point differs from current input target'
    return None


def native_music_hit_stability(original,fresh,requested):
    for pick in (original,fresh):
        reason=native_music_hit_blocker(pick,requested)
        if reason:return reason
    a,b=original['nativeMusicHit'],fresh['nativeMusicHit']
    if a['ownership']!=b['ownership']:return 'Native music model/camera/drag ownership changed across native inspection'
    if a['dragPlane']!=b['dragPlane']:
        return 'Native music drag-handler plane geometry changed across native inspection'
    identity=('ordinal','index','positionIndex','rectId','rectGameObjectId','typedRowId','typedVOId','liveMasterId','activeInHierarchy')
    if ([tuple(c.get(k) for k in identity) for c in a['orderedCells']]!=
        [tuple(c.get(k) for k in identity) for c in b['orderedCells']]):
        return 'Native music ordered cell/VO identities changed across native inspection'
    if ([c['nativeBounds'] for c in a['orderedCells']]!=[c['nativeBounds'] for c in b['orderedCells']] or
        a['listSignature']!=b['listSignature']):
        return 'Native music ordered native bounds changed across native inspection'
    return None


def music_adjustment_blocker(selection,requested):
    rows=[row for row in selection or [] if row.get('active') is True]
    if len(rows)!=1:return 'Await one actual current music controller and adjustment blocker'
    current=(rows[0].get('currentSelectedCellVO') or {}).get('liveMasterId')
    if current!=requested:return 'Await actual selected song %s; observed=%s'%(requested,current)
    blocker=rows[0].get('noteInputBlocker') or {}
    if blocker.get('resolved') is not True:return 'Await resolved actual music noteInputBlocker state'
    if blocker.get('activeInHierarchy') is not False:return 'Await native OnAdjustCell completion; actual noteInputBlocker remains active'
    return None


def download_song_target(tree,requested):
    if tree.get('screen',{}).get('scene')!='LiveMusicSelect' or requested is None:return None
    mv=(tree.get('features') or {}).get('mv') or {}
    if music_adjustment_blocker(mv.get('musicSelection'),requested):return None
    matches=[node for node in tree.get('nodes',[]) if node.get('kind')=='text' and
             node.get('path')==DOWNLOAD_SONG_PATH and node.get('text')=='Download Song' and
             all(node.get(k) is True for k in ('active','visible','enabled','groupsInteractable','blocksRaycasts')) and
             all((node.get('hit') or {}).get(k) is True for k in ('available','hittable'))]
    return matches[0] if len(matches)==1 else None
