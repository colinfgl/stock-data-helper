import unittest
from scripts.stock_receipt_native_writer_v1_20261018 import write_native_receipts, RECEIPT_FIELDS, OBS_FIELDS

class Fake:
    def __init__(self):
        self.data={'STOCK_Delivery_Receipt':[list(RECEIPT_FIELDS)],'STOCK_Delivery_Observability':[list(OBS_FIELDS)]}
    def read_rows(self,_,tab): return self.data[tab]
    def append_row(self,_,tab,row): self.data[tab].append(row)

class WriterTests(unittest.TestCase):
    def test_append_and_resume(self):
        db=Fake()
        a=['']*20;b=['']*22
        a[0:4]=['RUN-1','2026-10-19','STOCK_SETTLEMENT','a'*64]
        b[0:3]=['2026-10-19','STOCK_SETTLEMENT','TASK-1']
        b[13]='a'*64
        plan={'RunID':'RUN-1','TargetDate':'2026-10-19','ReportSHA':'a'*64,
              'Authority':'CURRENT_RUN_BYTES_ONLY_NO_AUTOMATIC_FORMAL_NATURAL',
              'NativeWriteStatus':'NOT_EXECUTED','ReceiptRow':a,'ObservabilityRow':b}
        actions={'AutoWriteAllowed':True,'ReceiptAction':'APPEND_REQUIRED','ObservabilityAction':'APPEND_REQUIRED'}
        with self.assertRaises(PermissionError):
            write_native_receipts(plan=plan,actions=actions,client=db,spreadsheet_id='S',lease_token='',lease_verified=False)
        out=write_native_receipts(plan=plan,actions=actions,client=db,spreadsheet_id='S',lease_token='T',lease_verified=True)
        self.assertEqual(out['STOCK_Delivery_Receipt'],'APPEND_READBACK_PASS')
        out=write_native_receipts(plan=plan,actions=actions,client=db,spreadsheet_id='S',lease_token='T',lease_verified=True)
        self.assertEqual(out['STOCK_Delivery_Receipt'],'NO_OP_READBACK_PASS')
        self.assertEqual(len(db.data['STOCK_Delivery_Receipt']),2)
        # Sheets may omit physically empty trailing cells on readback.
        db.data['STOCK_Delivery_Receipt'][1] = db.data['STOCK_Delivery_Receipt'][1][:19]
        with self.assertRaises(ValueError):
            write_native_receipts(plan=plan,actions=actions,client=db,spreadsheet_id='S',lease_token='T',lease_verified=True)
        db.data['STOCK_Delivery_Receipt'][1] = a.copy()
        db.data['STOCK_Delivery_Observability'][1][13]='b'*64
        with self.assertRaises(ValueError):
            write_native_receipts(plan=plan,actions=actions,client=db,spreadsheet_id='S',lease_token='T',lease_verified=True)

if __name__=='__main__':unittest.main()
