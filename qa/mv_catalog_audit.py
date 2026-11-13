"""Observe the same character's complete displayed suit catalog before/after MV.

Plans are ordinary UI actions; no game callbacks, setters or synthesized data.
Raw row multiplicities are preserved, including any preexisting legacy clones.
"""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import time

from mv_driver import deck_layout, standing_count


def complete_catalog(tree,member):
    catalogs=[]
    for catalog in ((tree.get('features') or {}).get('mv') or {}).get('suitCatalogs',[]):
        if catalog.get('active') is not True or catalog.get('complete') is not True or catalog.get('memberId')!=member:continue
        rows=catalog.get('rows') or []
        if type(catalog.get('arrayLength')) is not int or not 0<len(rows)==catalog['arrayLength']<=5000:continue
        if any(type(row.get('memberId')) is not int or row['memberId']!=member or type(row.get('suitId')) is not int or row['suitId']<=0 for row in rows):continue
        catalogs.append(catalog)
    return catalogs[0] if len(catalogs)==1 else None


class SuitCatalogAudit:
    def __init__(self,evidence):
        self.evidence=Path(evidence);self.phase='before-open';self.original=None
        self.position=self.member=None;self.first=None;self.baseline=None;self.after=None
        self.started=None;self.references={};self.done=False

    @property
    def ready(self):return self.phase=='before-done' or self.done

    def start_after(self):
        if self.phase=='before-done':self.phase='after-open';self.started=None;self.first=None

    def _reference(self,relative):
        path=(self.evidence/relative).resolve(strict=True)
        assert path.is_relative_to(self.evidence.resolve())
        return {'path':relative,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

    def _save(self,side,catalog,first_path,second_path):
        relative='mv-complete-client-catalog-'+side+'.json'
        data={'memberId':self.member,'rows':catalog['rows'],'arrayLength':catalog['arrayLength'],
              'binding':catalog,'snapshots':[self._reference(first_path),self._reference(second_path)],
              'scope':'Complete actual displayed MemberSuitVO array; raw multiplicities, no deduplication'}
        (self.evidence/relative).write_text(json.dumps(data,indent=2)+'\n');self.references[side]=self._reference(relative)

    def step(self,tree,relative,*,now=None):
        now=time.monotonic() if now is None else now
        if self.phase=='before-done' or self.done:return None
        scene=(tree.get('screen') or {}).get('scene')
        layout=deck_layout(tree)
        if self.phase in ('before-open','after-open'):
            if scene!='LiveMvDeckSelect' or not layout or standing_count(tree)!=12:return None
            if self.original is None:
                self.original=copy.deepcopy(layout);self.position=min(layout);self.member=layout[self.position]['memberId']
            if layout!=self.original:raise RuntimeError('Opening client-catalog audit would use a changed original MV deck')
            self.started=now;self.first=None;self.phase=self.phase.replace('open','wait')
            return {'kind':'pickmv','query':{'role':'suit','formationPosition':self.position},
                    'reason':'Inspect complete same-character closet before any duplicate edit' if self.phase.startswith('before') else 'Inspect same-character closet after restored MV deck'}
        if self.started is not None and now-self.started>60:
            raise RuntimeError('Complete displayed client suit catalog was not observed/closed within60seconds: '+self.phase)
        catalogs=((tree.get('features') or {}).get('mv') or {}).get('suitCatalogs',[])
        if self.phase.endswith('-wait'):
            catalog=complete_catalog(tree,self.member)
            if catalog is None:return {'kind':'wait','seconds':.3,'reason':'Await complete displayed array identity and all raw suit rows'}
            stamp=(catalog.get('id'),catalog['rows'])
            if self.first is None or self.first[0]!=stamp:
                self.first=(copy.deepcopy(stamp),relative);return {'kind':'wait','seconds':.3,'reason':'Require a second actual stable complete client catalog'}
            side=self.phase.split('-')[0]
            self._save(side,catalog,self.first[1],relative)
            if side=='before':self.baseline=copy.deepcopy(catalog['rows'])
            else:
                self.after=copy.deepcopy(catalog['rows'])
                key=lambda row:(row['memberId'],row['suitId'])
                if Counter(map(key,self.baseline))!=Counter(map(key,self.after)):
                    raise RuntimeError('Same-character complete client closet changed after duplicate MV selection (raw ID multiplicities differ)')
            self.phase=side+'-close'
            return {'kind':'key','key':'KEYCODE_BACK','reason':'Close only the actually observed suit popup without changing its selected costume'}
        if self.phase.endswith('-close'):
            if any(c.get('active') is True for c in catalogs):return {'kind':'wait','seconds':.3,'reason':'Await ordinary suit-popup close'}
            if scene!='LiveMvDeckSelect' or layout!=self.original:
                raise RuntimeError('Catalog inspection changed or failed to restore the entire original custom MV deck')
            if self.phase.startswith('before'):self.phase='before-done'
            else:self.phase='done';self.done=True
            return {'kind':'audit-ready','reason':'Actual complete catalog stable and entire custom deck unchanged'}
        raise RuntimeError('Unexpected client catalog audit phase')

    def result(self):
        return {'status':'PASS' if self.done else 'NOT_RUN','memberId':self.member,
                'before_count':len(self.baseline) if self.baseline is not None else None,
                'after_count':len(self.after) if self.after is not None else None,
                'evidence':self.references,'phase':self.phase,
                'scope':'Same-character complete displayed catalog before FIRST duplicate edit and after restored/reopened MV; preserves preexisting raw duplicates'}
