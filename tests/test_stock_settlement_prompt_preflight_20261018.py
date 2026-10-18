import hashlib
import unittest
from scripts.stock_settlement_prompt_preflight_20261018 import check

BODY='執行 STOCK_SETTLEMENT（R151.6 FINAL-v17）。'
REQUIRED=('TerminalizerNativeProtocol', 'TerminalizerSourceRepository', 'TerminalizerSourceCommit', 'TerminalizerPythonSHA256', 'GovernanceSuccessorHandoff', 'NextConfigExecutableHandoff', 'H9SecondaryBaselineReadRoute')

def snapshot():
    fields=['BootstrapBodySHA256='+hashlib.sha256(BODY.encode()).hexdigest()]
    fields += [k+'='+('f'*64 if k=='TerminalizerPythonSHA256' else 'verified-'+k) for k in REQUIRED]
    return dict(id='6a825a73808c81918c5c7b5d1fecaf28', prompt='\n'.join(fields)+'\n---BOOTSTRAP_BODY---\n'+BODY,
                schedule='weekdays 19:00',is_enabled=True,timing_mode='exact_schedule',notifications_enabled=True,email_enabled=True)

class SettlementPreflightTests(unittest.TestCase):
    def test_exact(self):
        s=snapshot();self.assertEqual(check(s,s.copy()),[])
    def test_truncated(self):
        s=snapshot();t=s.copy();t['prompt']=t['prompt'][:50];self.assertIn('PROMPT_LENGTH_REGRESSION',check(s,t))
    def test_body_changed(self):
        s=snapshot();t=s.copy();t['prompt']+='x';self.assertIn('IMMUTABLE_BODY_CHANGED',check(s,t))
    def test_hash_changed(self):
        s=snapshot();t=s.copy();t['prompt']=t['prompt'].replace('BootstrapBodySHA256=','BootstrapBodySHA256=0');self.assertIn('PROPOSED_BOOTSTRAP_SHA_MISMATCH',check(s,t))
    def test_schedule(self):
        s=snapshot();t=s.copy();t['schedule']='other';self.assertIn('UNAUTHORIZED_CHANGE_schedule',check(s,t))
    def test_notification(self):
        s=snapshot();t=s.copy();t['email_enabled']=False;self.assertIn('UNAUTHORIZED_CHANGE_email_enabled',check(s,t))
    def test_incomplete_original(self):
        s=snapshot();t=s.copy();s['prompt']=s['prompt'].replace('TerminalizerNativeProtocol=verified-TerminalizerNativeProtocol\n','');self.assertIn('ORIGINAL_EMPTY_OR_MISSING_TerminalizerNativeProtocol',check(s,t))
    def test_missing_supplement(self):
        s=snapshot();t=s.copy();t['prompt']=t['prompt'].replace('NextConfigExecutableHandoff=verified-NextConfigExecutableHandoff\n','');self.assertIn('PROPOSED_EMPTY_OR_MISSING_NextConfigExecutableHandoff',check(s,t))
    def test_fake_required_inside_body(self):
        s=snapshot();t=s.copy();t['prompt']=t['prompt'].replace('GovernanceSuccessorHandoff=verified-GovernanceSuccessorHandoff\n','');t['prompt']+='\nGovernanceSuccessorHandoff=pretend';self.assertIn('PROPOSED_EMPTY_OR_MISSING_GovernanceSuccessorHandoff',check(s,t))
    def test_empty_fields(self):
        s=snapshot();t=s.copy();t['prompt']=t['prompt'].replace('TerminalizerNativeProtocol=verified-TerminalizerNativeProtocol','TerminalizerNativeProtocol=');self.assertIn('PROPOSED_EMPTY_OR_MISSING_TerminalizerNativeProtocol',check(s,t))
    def test_duplicate_sha(self):
        s=snapshot();t=s.copy();t['prompt']='BootstrapBodySHA256='+'a'*64+'\n'+t['prompt'];self.assertIn('PROPOSED_DUPLICATE_KEY_BootstrapBodySHA256',check(s,t))
    def test_protected_value_changed(self):
        s=snapshot();t=s.copy();t['prompt']=t['prompt'].replace('verified-NextConfigExecutableHandoff','new-value-NextConfigExecutableHandoff');self.assertIn('PROTECTED_FIELD_CHANGED_NextConfigExecutableHandoff',check(s,t))
if __name__=='__main__':unittest.main()