"""Strict parsing of read-only semantic-pick refusals; never authorizes input."""
import json
import re

ERRORS={'No active semantic UI target':'SEMANTIC_TARGET_UNAVAILABLE',
        'Ambiguous active semantic UI targets':'SEMANTIC_TARGET_AMBIGUOUS'}


def semantic_pick_refusal(error,expected_query):
    """Caller must first require the actual Frida RPCException type."""
    raw=str(error)
    if len(raw)>512*1024 or not raw.startswith('Error: '):return None
    try:payload,end=json.JSONDecoder().raw_decode(raw[7:])
    except (ValueError,TypeError):return None
    remainder=raw[7+end:]
    if remainder.strip() and not all(re.fullmatch(r'\s+at [^\r\n]+',line) for line in remainder.splitlines() if line):return None
    required={'error','query','matches','screen','hitTest','diagnostics'}
    if (type(payload) is not dict or not required.issubset(payload) or
        type(payload.get('error')) is not str or payload.get('error') not in ERRORS or payload.get('query')!=expected_query or
        type(payload['matches']) is not list or type(payload['screen']) is not dict or
        type(payload['hitTest']) is not dict or type(payload['diagnostics']) is not list):return None
    if 'errorCode' in payload and payload['errorCode']!=ERRORS[payload['error']]:return None
    if payload['error']=='No active semantic UI target' and payload['matches']:return None
    if payload['error']=='Ambiguous active semantic UI targets' and not payload['matches']:return None
    return {'raw_error':raw,'query':dict(expected_query),'pick_snapshot':payload,
            'input_performed':False,'scope':'Read-only target availability observation; no cause or input retry is inferred'}


def classified_semantic_refusal(error,query,*,rpc_exception_type,predeck):
    if not predeck or not isinstance(error,rpc_exception_type):return None
    return semantic_pick_refusal(error,query)


def music_selection_witness(value,requested):
    """Both exact metadata fields are observations, not completion predicates."""
    rows=value if type(value) is list else []
    active=[row for row in rows if type(row) is dict and row.get('active') is True]
    row=active[0] if len(active)==1 else {}
    current_vo=row.get('currentSelectedCellVO');decided_vo=row.get('decidedCellVO')
    current=current_vo.get('liveMasterId') if type(current_vo) is dict else None
    decided=decided_vo.get('liveMasterId') if type(decided_vo) is dict else None
    return {'requested_song_id':requested,'active_controller_count':len(active),
            'observed_current_selected_song_id':current,'observed_decided_song_id':decided,
            'current_selected_matches_requested':requested is not None and current==requested and type(current) in (int,float),
            'scope':'Direct existing CellVO fields only; decided/write timing and MV-download readiness are not inferred'}


def music_selection_blocker(tree,requested):
    if tree.get('screen',{}).get('scene')!='LiveMusicSelect' or requested is None:return None
    values=((tree.get('features') or {}).get('mv') or {}).get('musicSelection')
    observed=music_selection_witness(values,requested)
    if not observed['current_selected_matches_requested']:
        return 'Await read-only currentSelectedCellVO LiveMasterId matching requested song intent %s; observed=%s controllers=%s'%(
            requested,observed['observed_current_selected_song_id'],observed['active_controller_count'])
    return None
