"""Read-only agreement of two typed music picks across native inspection."""
import math


def music_target_stability(original,fresh,query,*,tolerance=2):
    """No input is eligible while the projected row is moving or recycled."""
    result={'stable':False,'tolerance_px':tolerance,'deltas_px':{}}
    if query.get('role')!='music' or type(query.get('liveMasterId')) is not int:
        return dict(result,reason='Missing exact typed music query')
    for pick in (original,fresh):
        catalog=pick.get('catalog') or {}
        if catalog.get('liveMasterId')!=query['liveMasterId'] or catalog.get('isPlayable') is not True:
            return dict(result,reason='Typed music VO changed before input')
    old,new=original.get('target') or {},fresh.get('target') or {}
    if (not old.get('id') or not old.get('path') or
        any(old.get(key)!=new.get(key) for key in ('id','path')) or
        any((original.get('screen') or {}).get(key)!=(fresh.get('screen') or {}).get(key)
            for key in ('scene','width','height'))):
        return dict(result,reason='Typed music scene/path/instance/surface changed before input')
    for name,keys in (('center',('x','y')),('bounds',('left','top','right','bottom')),
                      ('visibleBounds',('left','top','right','bottom'))):
        a,b=old.get(name),new.get(name)
        if name=='visibleBounds' and a is None and b is None:continue
        if not isinstance(a,dict) or not isinstance(b,dict):
            return dict(result,reason='Typed music projected geometry unavailable')
        for key in keys:
            x,y=a.get(key),b.get(key)
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (x,y)):
                return dict(result,reason='Typed music projected geometry unavailable')
            result['deltas_px'][name+'.'+key]=abs(x-y)
    if any(delta>tolerance for delta in result['deltas_px'].values()):
        return dict(result,reason='Typed music projected row is still moving; no input')
    return dict(result,stable=True,reason='Two fresh typed music picks agree across native inspection')
