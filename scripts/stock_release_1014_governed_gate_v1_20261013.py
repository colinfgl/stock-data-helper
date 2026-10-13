#!/usr/bin/env python3
"""2026-10-14 candidate-only governable stock handoff validator.

Consumes only *provided* native receipt snapshots. Does not contact Google/GitHub,
write spreadsheets, seal Config, alter tasks, score outcomes or place orders.
Separates NEXT_CONFIG, SOURCE, PREDICTION, NATURAL and DELIVERY evidence gates.
Production use requires live tool readback; a JSON fixture is never proof of it.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

TARGET = '2026-10-14'
YESTERDAY = '2026-10-13'
REQUIRED = ('target_date','source_date','official_calendar','identity','prior_settlement',
            'current_todo','next_config','evening_source','original_h9','formal_basis',
            'same_run_prediction','delivery','cash')
SHA = re.compile(r'^[0-9a-f]{64}$')

class Hold(ValueError):
    pass

def digest(payload:bytes)->str:
    return hashlib.sha256(payload).hexdigest()

def valid_sha(s):
    return isinstance(s,str) and bool(SHA.fullmatch(s))

def stamped_before(sealed, start):
    try:
        return dt.datetime.fromisoformat(sealed.replace('Z','+00:00')) < dt.datetime.fromisoformat(start.replace('Z','+00:00'))
    except (ValueError,AttributeError,TypeError):
        return False

def evaluate(x):
    if not isinstance(x,dict) or any(k not in x for k in REQUIRED):
        raise Hold('INPUT_SCHEMA_REQUIRED_FIELDS')
    if x['target_date'] != TARGET or x['source_date']!=YESTERDAY:
        raise Hold('TARGET_OR_SOURCE_DATE_DRIFT')
    gates={}
    def mark(gate,ok,reason):
        gates[gate]={'status':'PASS' if ok else 'HOLD','reason':'PASS' if ok else reason}
    cal=x['official_calendar'];ident=x['identity'];p=x['prior_settlement']
    mark('CALENDAR',cal.get('target_date')==TARGET and cal.get('is_trading_day') is True and valid_sha(cal.get('original_sha')),
         'OFFICIAL_20261014_CALENDAR_OR_SHA_MISSING')
    mark('TASK_IDENTITY',ident.get('one_enabled_premarket') is True and ident.get('one_enabled_settlement') is True and
         ident.get('prior_task_identity_matches') is True and ident.get('bootstrap_sha_verified') is True,
         'LIVE_TASK_ID_OR_BOOTSTRAP_SHA_DRIFT')
    prior_ok=(p.get('date')==YESTERDAY and p.get('normal_schedule') is True and p.get('final_receipt_readback') is True and
        p.get('native_20_readback') is True and p.get('native_22_readback') is True and
        valid_sha(p.get('original_report_sha')) and p.get('same_runid_both_native') is True)
    mark('PRIOR_SETTLEMENT_TERMINAL',prior_ok,'REQUIRES_GENUINE_20261013_1900_SAME_RUN_FINAL_20_22_READBACK')
    e=x['current_todo'];ent=(e.get('same_fixed_ids') is True and e.get('same_revision') is True and e.get('both_live_readback') is True)
    mark('CURRENT_TODO',ent,'CURRENT_TODO_FIXED_IDS_R29_R33_SYNC_PENDING')
    n=x['next_config'];cfg=(n.get('target_date')==TARGET and n.get('unique_presealed_count')==1 and
        n.get('governance_hash_recomputed') is True and n.get('hash_matches_native') is True and
        n.get('prompt_bundle_task_binding_verified') is True and valid_sha(n.get('config_hash')) and
        stamped_before(n.get('sealed_at'), n.get('scheduled_start')))
    mark('NEXT_CONFIG',cfg,'20261014_UNIQUE_PRESEALED_HASH_AND_PRESTART_READBACK_REQUIRED')
    # A scheduled transfer may become eligible only with true previous settlement
    # and a governance-consistent pointer. Fresh stock prices are a *separate*
    # model qualification check: missing provider source must NOT erase research.
    mark('CUTOVER_ELIGIBLE',prior_ok and ent and cfg and gates['TASK_IDENTITY']['status']=='PASS' and gates['CALENDAR']['status']=='PASS',
         'NO_GOVERNED_CUTOVER_WITHOUT_SETTLEMENT_ENTRY_CONFIG_AND_CALENDAR')
    s=x['evening_source'];source=(s.get('for_target')==TARGET and s.get('last_trading_day')==YESTERDAY and
      s.get('official_primary_count')==3 and s.get('provider_count')==68 and s.get('unique_original_sha_count')==71 and
      valid_sha(s.get('package_sha')) and s.get('original_raw_readback') is True and s.get('no_after_cutoff_rows') is True)
    mark('FRESH_NEXT_SESSION_SOURCE',source,'20261013_2045_RAW68_OFFICIAL3_SHA71_TRUE_RUN_NOT_YET_VERIFIED')
    m=x['original_h9'];program=(valid_sha(m.get('original_model_sha')) and m.get('original_immutable_sha_verified') is True and
        m.get('binary_exec_in_actual_worker') is True and m.get('actual_runid_binds_source') is True)
    mark('ORIGINAL_H9_SAME_WORKER',program,'GITHUB_CODE_MAIN_NOT_INSTALLED_IN_CHATGPT_0810_WORKER')
    b=x['formal_basis'];basis=(b.get('all_used_symbol_basis_audited') is True and b.get('issuer_actions_qualified') is True and
       b.get('basis_date_before_start') is True)
    mark('FORMAL_BASIS',basis,'COMPLETE_ISSUER_ACTION_BASIS_AUDIT_NOT_YET_CERTIFIED')
    pp=x['same_run_prediction'];pred=(pp.get('target_date')==TARGET and pp.get('before_start') is True and
        pp.get('actual_normal_schedule') is True and pp.get('native_prediction_key_sha_readback') is True and
        pp.get('same_runid_cutoff_model_source') is True and valid_sha(pp.get('forecast_sha')))
    mark('NATIVE_FORECAST_SEAL',pred,'GENUINE_20261014_SAME_RUN_NATIVE_PREDICTIONKEY_FORECASTSHA_NOT_DONE')
    formal=(gates['CUTOVER_ELIGIBLE']['status']=='PASS' and source and program and basis and pred)
    mark('FORMAL_ELIGIBLE',formal,'REQUIRES_ALL_SOURCE_MODEL_BASIS_NATIVE_SEAL_GATES')
    d=x['delivery'];delivered=(d.get('same_report_sha') is True and d.get('platform_message_reference') and
        d.get('platform_delivery_timestamp') and d.get('platform_trigger_receipt'))
    mark('PLATFORM_DELIVERED_VERIFIED',bool(delivered),'PLATFORM_MESSAGE_DELIVERY_TRIGGER_NOT_EXPOSED')
    natural=(formal and d.get('natural_1900_same_run_final') is True and d.get('same_run_save_readback') is True and
        gates['PLATFORM_DELIVERED_VERIFIED']['status']=='PASS')
    mark('NATURAL_ELIGIBLE',natural,'TRUE_TWO_SCHEDULED_RUNS_SAVE_READBACK_PLATFORM_PROOF_PENDING')
    cash=x['cash'];allowed=(cash.get('cash7_primary_verified') is True and cash.get('broker_trade_bills_verified') is True)
    mark('CASH_ORDER_ELIGIBLE',allowed,'BROKER_CASH7_PRIMARY_NOT_VERIFIED_0_EXECUTABLE_SHARES')
    return {
      'status':'FORMAL_READY' if formal else 'RESEARCH_CAN_SHOW_VALUES_WITH_HOLD',
      'target_date':TARGET,'source_date':YESTERDAY,
      'can_publish_partial_report':True,'can_pretend_old_h9_is_new':False,
      'can_authorize_cash_order':allowed,
      'can_cutover':gates['CUTOVER_ELIGIBLE']['status']=='PASS',
      'formal_eligible':formal,'natural_eligible':natural,
      'gates':gates,
      'scope':'CANDIDATE_EVIDENCE_DIAGNOSTIC_ONLY_NEVER_WRITES_NATIVE',
    }

def fixture(positive=False):
    cfgsha='1'*64
    data={
      'target_date':TARGET,'source_date':YESTERDAY,
      'official_calendar':{'target_date':TARGET,'is_trading_day':True,'original_sha':cfgsha if positive else None},
      'identity':{'one_enabled_premarket':True,'one_enabled_settlement':True,'prior_task_identity_matches':True,'bootstrap_sha_verified':True},
      'prior_settlement':{'date':YESTERDAY,'normal_schedule':True,'final_receipt_readback':positive,
        'native_20_readback':positive,'native_22_readback':positive,'original_report_sha':cfgsha if positive else None,
        'same_runid_both_native':positive},
      'current_todo':{'same_fixed_ids':True,'same_revision':positive,'both_live_readback':positive},
      'next_config':{'target_date':TARGET,'unique_presealed_count':1 if positive else 0,'governance_hash_recomputed':positive,
          'hash_matches_native':positive,'prompt_bundle_task_binding_verified':positive,
          'config_hash':cfgsha if positive else None,
          'sealed_at':'2026-10-13T20:55:00+08:00' if positive else None,
          'scheduled_start':'2026-10-14T08:10:00+08:00'},
      'evening_source':{'for_target':TARGET,'last_trading_day':YESTERDAY,'official_primary_count':3 if positive else 0,
        'provider_count':68 if positive else 0,'unique_original_sha_count':71 if positive else 0,
        'package_sha':cfgsha if positive else None,'original_raw_readback':positive,'no_after_cutoff_rows':positive},
      'original_h9':{'original_model_sha':cfgsha,'original_immutable_sha_verified':True,
        'binary_exec_in_actual_worker':positive,'actual_runid_binds_source':positive},
      'formal_basis':{'all_used_symbol_basis_audited':positive,'issuer_actions_qualified':positive,'basis_date_before_start':positive},
      'same_run_prediction':{'target_date':TARGET,'before_start':positive,'actual_normal_schedule':positive,
         'native_prediction_key_sha_readback':positive,'same_runid_cutoff_model_source':positive,
         'forecast_sha':cfgsha if positive else None},
      'delivery':{'same_report_sha':positive,'platform_message_reference':'M' if positive else None,
         'platform_delivery_timestamp':'T' if positive else None,'platform_trigger_receipt':'R' if positive else None,
         'natural_1900_same_run_final':positive,'same_run_save_readback':positive},
      'cash':{'cash7_primary_verified':positive,'broker_trade_bills_verified':positive}
    }
    return data

def selftest():
    t={}
    def pass_test(name,ok):t[name]='PASS' if ok else 'FAIL'
    neg=evaluate(fixture(False));pos=evaluate(fixture(True))
    pass_test('false_fixture_research_not_formal',not neg['formal_eligible'] and neg['can_publish_partial_report'])
    pass_test('false_fixture_never_cash',not neg['can_authorize_cash_order'])
    pass_test('false_fixture_no_natural',not neg['natural_eligible'])
    pass_test('positive_fixture_formal',pos['formal_eligible'])
    pass_test('positive_fixture_natural',pos['natural_eligible'])
    pass_test('positive_fixture_cash',pos['can_authorize_cash_order'])
    for name,key,val,expected in [
      ('block_noncalendar','official_calendar','is_trading_day',False),
      ('block_wrong_priorday','prior_settlement','date','2026-10-12'),
      ('block_manual_predecessor','prior_settlement','normal_schedule',False),
      ('block_native20_missing','prior_settlement','native_20_readback',False),
      ('block_native22_missing','prior_settlement','native_22_readback',False),
      ('block_entry_divergence','current_todo','same_revision',False),
      ('block_zero_configs','next_config','unique_presealed_count',0),
      ('block_bad_configsha','next_config','config_hash','bad'),
      ('block_source67','evening_source','provider_count',67),
      ('block_source_70shas','evening_source','unique_original_sha_count',70),
      ('block_postcutoff_source','evening_source','no_after_cutoff_rows',False),
      ('block_worker_absent','original_h9','binary_exec_in_actual_worker',False),
      ('block_issuer_actions','formal_basis','issuer_actions_qualified',False),
      ('block_prediction_no_write','same_run_prediction','native_prediction_key_sha_readback',False),
      ('block_prediction_wrong_run','same_run_prediction','same_runid_cutoff_model_source',False)
    ]:
        x=fixture(True);x[key][val]=expected
        pass_test(name,not evaluate(x)['formal_eligible'])
    x=fixture(True);x['delivery']['platform_message_reference']=None
    pass_test('no_message_no_natural',not evaluate(x)['natural_eligible'] and evaluate(x)['formal_eligible'])
    x=fixture(True);x['next_config']['sealed_at']='2026-10-14T08:11:00+08:00'
    pass_test('block_after_start_seal',not evaluate(x)['formal_eligible'])
    x=fixture(True);x['cash']['cash7_primary_verified']=False
    pass_test('no_cash_without_broker',not evaluate(x)['can_authorize_cash_order'] and evaluate(x)['formal_eligible'])
    x=fixture(True);x['official_calendar']['original_sha']='BAD'
    pass_test('reject_calendar_sha',not evaluate(x)['formal_eligible'])
    try:evaluate({'target_date':TARGET}); pass_test('reject_incomplete_schema',False)
    except Hold:pass_test('reject_incomplete_schema',True)
    try:x=fixture(True);x['source_date']='2026-10-12';evaluate(x);pass_test('reject_relabel_old_session',False)
    except Hold:pass_test('reject_relabel_old_session',True)
    return {'status':'PASS' if all(x=='PASS' for x in t.values()) else 'FAIL','total':len(t),
            'passed':sum(x=='PASS' for x in t.values()),'tests':t,
            'scope':'PURE_SYNTHETIC_NO_PRIVATE_INPUT_NO_MODEL_CHANGE_NO_NATIVE_WRITE'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--input');p.add_argument('--out')
    a=p.parse_args()
    if a.self_test:r=selftest()
    else:
        if not a.input: p.error('--input is required without --self-test')
        r=evaluate(json.loads(Path(a.input).read_text(encoding='utf8')))
    s=json.dumps(r,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
    if a.out:Path(a.out).write_text(s,encoding='utf8')
    print(s)
    return 0 if a.self_test and r['status']=='PASS' else 0

if __name__=='__main__':raise SystemExit(main())
