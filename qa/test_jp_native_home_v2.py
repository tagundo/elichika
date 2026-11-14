"""Affected runner integration only; source fakes never qualify a game feature."""
from pathlib import Path
import unittest

import jp_chooser_scroll as chooser
import jp_light_adapter as light
from jp_capture_guard import StopCapture
from jp_native_home_capture import require_planned_input


OWNED={'pid':1911,'start_ticks':'40934'}


def capture(suffix,identifier,native,captured):
    root=Path(__file__).parent/'fixtures'
    raw=(root/('actual-jp-home-v1-'+suffix+'.png')).read_bytes()
    xml=(root/('actual-jp-home-v1-'+suffix+'.xml')).read_bytes()
    return {'id':identifier,'png_bytes':raw,'png_sha256':light.exact.digest(raw),
        'native_xml':xml,'native_sha256':light.exact.digest(xml),
        'native_at':native,'captured_at':captured,'identity_before':dict(OWNED),
        'identity_after':dict(OWNED),'activity':'com.klab.lovelive.allstars.MainActivity',
        'activity_at':captured+.1}


class RunnerScrollIntegrationTests(unittest.TestCase):
    def test_reserved_actual_scroll_revalidates_both_endpoints_without_second_budget_spend(self):
        a,b=capture('038','first',10.0,10.5),capture('039','second',11.0,11.5)
        budget=chooser.ChooserScrollBudget();persisted=[]
        options={'owned_identity':OWNED,'current_identity':OWNED,'now':12.0,
            'overall_started':0.0,'settings_started':1.0}
        reserved=budget.reserve(a,b,persist=persisted.append,**options)
        self.assertEqual(len(persisted),1)
        final=chooser.plan_pair(a,b,**options)
        require_planned_input(final,reserved['kind'],reserved['start'],reserved['end'])
        self.assertEqual(budget.attempts,1)
        for point,end in (([reserved['start'][0]+1,reserved['start'][1]],reserved['end']),
                (reserved['start'],[reserved['end'][0],reserved['end'][1]-1])):
            with self.subTest(point=point,end=end),self.assertRaises(StopCapture):
                require_planned_input(final,reserved['kind'],point,end)

    def test_partial_scroll_proof_cannot_authorize_Light_or_survive_input_boundary_expiry(self):
        a,b=capture('038','first',10.0,10.5),capture('039','second',11.0,11.5)
        options={'owned_identity':OWNED,'current_identity':OWNED,'now':12.0,
            'overall_started':0.0,'settings_started':1.0}
        plan=chooser.plan_pair(a,b,**options)
        self.assertEqual(plan['kind'],'diagnostic-chooser-upward-scroll')
        with self.assertRaises(StopCapture):
            require_planned_input(plan,'choose-light',plan['center'])
        with self.assertRaises(light.Refusal):light.plan_pair(a,b,state='bulk',**options)
        options['now']=19.0
        with self.assertRaises(light.Refusal):chooser.plan_pair(a,b,**options)


if __name__=='__main__':unittest.main()
