"""Acceptance tests for MediMate (run: python -m unittest discover -s tests -v)."""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import database as db
from medimate_core import ValidationError, expiry_label, local_today, parse_clock, recording_rate, schedule_on_date

Z = "Asia/Jakarta"


class MediMateAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.configure_data_dir(self.tmp.name)
        db.initialize()
        self.today = local_today(Z)

    def tearDown(self):
        self.tmp.cleanup()

    def med(self, stock=10, expiry_days=90, low=3, name="Obat Dummy"):
        return db.add_medicine(name,"Tablet","Label fiktif",stock,low,
                               (self.today+timedelta(days=expiry_days)).isoformat(),"Uji",Z)

    def schedule(self, mid=None, at="08:00", qty=2, start=None, end=None):
        mid = mid if mid else self.med()
        db.add_schedule(mid,at,qty,start or (self.today-timedelta(days=4)).isoformat(),end,Z)
        return db.rows("SELECT id FROM schedules ORDER BY id DESC LIMIT 1")[0]["id"]

    def stock(self, mid):
        return db.stock_snapshot(self.today)[0]["stock_usable"] if len(db.stock_snapshot(self.today))==1 else next(m["stock_usable"] for m in db.stock_snapshot(self.today) if m["id"]==mid)

    def test_T01_add_medicine(self):
        mid=self.med()
        self.assertEqual(db.medicine_list()[0]["id"],mid)
        self.assertEqual(self.stock(mid),10)

    def test_T02_blank_name(self):
        with self.assertRaisesRegex(ValidationError,"kosong"):
            self.med(name="  ")

    def test_T03_two_schedules(self):
        mid=self.med()
        self.schedule(mid,"08:00")
        self.schedule(mid,"20:00")
        self.assertEqual([r["at_time"] for r in db.day_events(self.today)], ["08:00","20:00"])

    def test_T04_taken_deducts_once(self):
        mid=self.med()
        sid=self.schedule(mid)
        db.record_intake(sid,self.today,"taken",Z)
        self.assertEqual(self.stock(mid),8)
        self.assertEqual(len(db.log_history()),1)

    def test_T05_double_click_idempotent(self):
        mid=self.med()
        sid=self.schedule(mid)
        db.record_intake(sid,self.today,"taken",Z)
        db.record_intake(sid,self.today,"taken",Z)
        self.assertEqual(self.stock(mid),8)
        self.assertEqual(len(db.log_history()),1)

    def test_T06_skipped_no_stock_reduction(self):
        mid=self.med()
        sid=self.schedule(mid)
        db.record_intake(sid,self.today,"skipped",Z)
        self.assertEqual(self.stock(mid),10)

    def test_T07_unrecorded_not_skipped(self):
        sid=self.schedule()
        self.assertEqual(db.day_events(self.today)[0]["status"],"unrecorded")
        self.assertEqual(len(db.log_history()),0)

    def test_T08_expiry_tomorrow(self):
        self.assertEqual(expiry_label(self.today+timedelta(days=1),self.today),"Mendekati kedaluwarsa")

    def test_T09_expiry_yesterday(self):
        self.assertEqual(expiry_label(self.today-timedelta(days=1),self.today),"Kedaluwarsa")
        mid=self.med(expiry_days=-1)
        self.assertEqual(self.stock(mid),0)

    def test_T10_low_stock(self):
        self.med(stock=3,low=3)
        self.assertTrue(db.stock_snapshot(self.today)[0]["low"])

    def test_T11_insufficient_stock_logged_without_negative(self):
        mid=self.med(stock=1,low=1)
        sid=self.schedule(mid,qty=2)
        msg=db.record_intake(sid,self.today,"taken",Z)
        self.assertIn("tanpa pengurangan",msg)
        self.assertEqual(self.stock(mid),1)
        self.assertEqual(db.log_history()[0]["stock_deducted"],0)

    def test_T12_export_import_roundtrip(self):
        mid=self.med()
        sid=self.schedule(mid)
        db.record_intake(sid,self.today,"taken",Z)
        old_stock=self.stock(mid)
        file=db.export_database()
        self.med(name='Obat Tambahan')
        self.assertEqual(len(db.medicine_list()),2)
        db.import_database(file,"RESTORE")
        self.assertEqual(len(db.medicine_list()),1)
        self.assertEqual(self.stock(mid),old_stock)
        self.assertEqual(len(db.log_history()),1)

    def test_T13_calendar_boundary(self):
        mid=self.med()
        start=(self.today-timedelta(days=1)).isoformat()
        end=self.today.isoformat()
        self.schedule(mid,start=start,end=end)
        self.assertEqual(len(db.day_events(self.today-timedelta(days=2))),0)
        self.assertEqual(len(db.day_events(self.today)),1)
        self.assertEqual(len(db.day_events(self.today+timedelta(days=1))),0)

    def test_T14_edit_and_cancel_restore_stock(self):
        mid=self.med()
        sid=self.schedule(mid)
        db.record_intake(sid,self.today,"taken",Z)
        self.assertEqual(self.stock(mid),8)
        db.record_intake(sid,self.today,"skipped",Z)
        self.assertEqual(self.stock(mid),10)
        db.record_intake(sid,self.today,"taken",Z)
        self.assertEqual(self.stock(mid),8)
        db.record_intake(sid,self.today,"clear",Z)
        self.assertEqual(self.stock(mid),10)
        self.assertEqual(len(db.log_history()),0)

    def test_FEFO_allocates_oldest_unexpired_first(self):
        mid=self.med(stock=1,expiry_days=30)
        db.add_batch(mid,4,(self.today+timedelta(days=100)).isoformat(),Z)
        sid=self.schedule(mid,qty=2)
        db.record_intake(sid,self.today,"taken",Z)
        batches=db.rows("SELECT qty FROM batches WHERE medicine_id=? ORDER BY expiry",(mid,))
        self.assertEqual([r["qty"] for r in batches],[0,3])

    def test_schedule_edit_after_log_rejected(self):
        mid=self.med()
        sid=self.schedule(mid)
        db.record_intake(sid,self.today,"taken",Z)
        with self.assertRaisesRegex(ValidationError,"riwayat"):
            db.update_schedule(sid,mid,"09:00",1,self.today.isoformat(),None)

    def test_archive_preserves_yesterday_and_hides_today(self):
        sid=self.schedule()
        db.archive_schedule(sid,Z)
        self.assertEqual(len(db.day_events(self.today)),0)
        self.assertEqual(len(db.day_events(self.today-timedelta(days=1))),1)

    def test_bad_import_does_not_replace_database(self):
        self.med()
        f=Path(self.tmp.name)/"bad.sqlite"
        f.write_text("not-a-sqlite-file")
        with self.assertRaises(ValidationError):
            db.import_database(str(f),"RESTORE")
        self.assertEqual(len(db.medicine_list()),1)

    def test_reject_duplicate_overlapping_schedule(self):
        mid=self.med()
        self.schedule(mid)
        with self.assertRaisesRegex(ValidationError,"sudah ada"):
            self.schedule(mid)

    def test_validations(self):
        self.assertEqual(parse_clock("20:00"),"20:00")
        with self.assertRaises(ValidationError):
            parse_clock("25:00")
        with self.assertRaises(ValidationError):
            self.med(stock=-2)
        self.assertAlmostEqual(recording_rate(2,4),50.0)


if __name__ == "__main__":
    unittest.main()


class FullNameProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        db.configure_data_dir(self.tmp.name)
        self.day=local_today(Z)

    def tearDown(self):
        self.tmp.cleanup()

    def test_profile_separation_and_same_full_name_retrieval(self):
        with db.use_profile('Dina Putri'):
            db.initialize()
            m=db.add_medicine('Obat Dina','Tablet','dummy',6,2,
                              (self.day+timedelta(days=31)).isoformat(),'test',Z)
            self.assertEqual(len(db.medicine_list()),1)
        with db.use_profile('Fitri Putri'):
            db.initialize()
            self.assertEqual(db.medicine_list(),[])
        with db.use_profile('  DINA   PUTRI  '):
            self.assertEqual(db.medicine_list()[0]['id'],m)
            self.assertEqual(db.medicine_list()[0]['name'],'Obat Dina')

    def test_profile_export_restore_scoped(self):
        with db.use_profile('alpha'):
            db.initialize()
            db.add_medicine('Obat Alpha','Tablet','dummy',6,2,
                            (self.day+timedelta(days=31)).isoformat(),'test',Z)
            backup=db.export_database()
        with db.use_profile('beta'):
            db.initialize()
            self.assertEqual(len(db.medicine_list()),0)
            db.import_database(backup,'RESTORE')
            self.assertEqual(len(db.medicine_list()),1)
        with db.use_profile('alpha'):
            self.assertEqual(len(db.medicine_list()),1)

    def test_invalid_names_rejected(self):
        for name in ('','a','../path','"evil"','<script>','    '):
            with self.assertRaises(ValidationError):
                db.profile_name(name)

    def test_full_name_normalization_and_display(self):
        self.assertEqual(db.profile_name('  Siti  Nurhaliza '), 'siti nurhaliza')
        self.assertEqual(db.profile_name('SITI NURHALIZA'), 'siti nurhaliza')
        self.assertEqual(db.display_name('  Siti   Nurhaliza  '), 'Siti Nurhaliza')
        self.assertEqual(db.display_name('Dina'), 'Dina')  # single-word names are accepted

    def test_timezone_choices_exactly_indonesia(self):
        from medimate_core import SUPPORTED_ZONES
        self.assertEqual(SUPPORTED_ZONES,('Asia/Jakarta','Asia/Makassar','Asia/Jayapura'))

class DailyIntakePlanTests(unittest.TestCase):
    """Daily frequency is represented as independent per-time events, not a daily flag."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.configure_data_dir(self.tmp.name)
        db.initialize()
        self.day = local_today(Z)
        self.expiry = (self.day+timedelta(days=60)).isoformat()
        self.start = (self.day-timedelta(days=2)).isoformat()

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, dose=1, freq=2, times=('08:00', '20:00')):
        return db.add_medicine_with_plan(
            'Obat A', 'Tablet', 'Dari label', 20, 5, self.expiry, 'Catatan',
            dose, freq, times, self.start, None, Z)

    def test_atomic_medication_and_plan_created_together(self):
        mid = self.create(dose=2)
        events = db.day_events(self.day)
        self.assertEqual([(x['at_time'], x['qty']) for x in events], [('08:00', 2), ('20:00', 2)])
        self.assertEqual([x['id'] for x in db.medicine_list()], [mid])

    def test_individual_confirmation_does_not_confirm_other_slot(self):
        mid = self.create(dose=2)
        events = db.day_events(self.day)
        db.record_intake(events[0]['schedule_id'],self.day,'taken',Z)
        now=db.day_events(self.day)
        self.assertEqual([x['status'] for x in now], ['taken','unrecorded'])
        self.assertEqual(db.stock_snapshot(self.day)[0]['stock_usable'], 18)
        db.record_intake(events[1]['schedule_id'],self.day,'taken',Z)
        self.assertEqual(db.stock_snapshot(self.day)[0]['stock_usable'], 16)

    def test_undo_single_slot_only_restores_its_units(self):
        self.create(dose=2)
        e=db.day_events(self.day)
        for item in e: db.record_intake(item['schedule_id'],self.day,'taken',Z)
        db.record_intake(e[0]['schedule_id'],self.day,'clear',Z)
        self.assertEqual([x['status'] for x in db.day_events(self.day)],['unrecorded','taken'])
        self.assertEqual(db.stock_snapshot(self.day)[0]['stock_usable'],18)

    def test_both_same_day_can_differ_in_status(self):
        self.create(dose=3)
        e=db.day_events(self.day)
        db.record_intake(e[0]['schedule_id'],self.day,'taken',Z)
        db.record_intake(e[1]['schedule_id'],self.day,'skipped',Z)
        self.assertEqual([x['status'] for x in db.day_events(self.day)], ['taken','skipped'])
        self.assertEqual(db.stock_snapshot(self.day)[0]['stock_usable'],17)

    def test_add_daily_plan_for_existing_medicine(self):
        mid=db.add_medicine('Obat B','Tablet','',10,2,self.expiry,'',Z)
        self.assertEqual(db.add_daily_plan(mid,1,3,['07:00','13:00','21:00'],self.start,'',Z),3)
        self.assertEqual([x['at_time'] for x in db.day_events(self.day)], ['07:00','13:00','21:00'])

    def test_reject_duplicate_times_without_creating_medicine(self):
        with self.assertRaises(ValidationError): self.create(times=['08:00','08:00'])
        self.assertEqual(db.medicine_list(),[])

    def test_reject_invalid_last_time_without_partial_creation(self):
        with self.assertRaises(ValidationError): self.create(times=['08:00','25:00'])
        self.assertEqual(db.medicine_list(),[])

    def test_reject_frequency_mismatch(self):
        with self.assertRaises(ValidationError): self.create(freq=3,times=['08:00','20:00'])
        self.assertEqual(db.medicine_list(),[])

    def test_reject_existing_schedule_conflict_atomically(self):
        self.create()
        mid=db.medicine_list()[0]['id']
        before=len(db.schedule_list())
        with self.assertRaises(ValidationError):
            db.add_daily_plan(mid,1,2,['07:00','20:00'],self.start,'',Z)
        self.assertEqual(len(db.schedule_list()),before)

    def test_ignore_unused_hidden_time_fields(self):
        self.create(freq=1,times=['09:00','invalid'])
        self.assertEqual(len(db.day_events(self.day)),1)
        self.assertEqual(db.day_events(self.day)[0]['at_time'],'09:00')

    def test_six_daily_intake_slots_limit(self):
        self.create(freq=6,times=['06:00','08:00','10:00','12:00','18:00','22:00'])
        self.assertEqual(len(db.day_events(self.day)),6)
        with self.assertRaises(ValidationError):
            self.create(freq=7,times=['06:00']*7)

    def test_edit_one_schedule_does_not_change_the_other(self):
        self.create()
        records=db.schedule_list()
        sid=next(r['id'] for r in records if r['at_time']=='08:00')
        mid=records[0]['medicine_id']
        db.update_schedule(sid,mid,'09:00',1,self.start,None)
        self.assertEqual([x['at_time'] for x in db.day_events(self.day)],['09:00','20:00'])

    def test_app_callbacks_create_and_display_independent_entries(self):
        import app
        with db.use_profile('Dina Putri'):
            db.initialize()
            msg=app.add_med('Obat A','Tablet','',20,5,self.expiry,'',Z,'id')
            self.assertIn('tab Jadwal',msg)
            self.assertEqual(len(app.choices_events(self.day.isoformat())),0)
            mid=db.medicine_list()[0]['id']
            msg=app.add_schedule(str(mid),2,'2','08:00','20:00','bad','bad','bad','bad',self.start,'',Z,'id')
            self.assertIn('2 jadwal',msg)
            self.assertEqual(len(app.choices_events(self.day.isoformat())),2)
        result=app.refresh_all('Dina Putri',Z,self.day.isoformat(),'7','id')
        self.assertEqual(len(result),20)
        self.assertEqual(result[16], 'Obat A')  # edit form prefills automatically
        self.assertEqual(result[17], '')
        self.assertEqual(result[18], 5)
        self.assertEqual(result[10]['value'],str(mid))

    def test_edit_medicine_selected_prefill_and_save(self):
        import app
        with db.use_profile('Dina Putri'):
            db.initialize()
            med1=db.add_medicine('Panadol','Tablet','500 mg',18,4,self.expiry,'Awal',Z)
            med2=db.add_medicine('Vitamin','Kapsul','20 mg',12,3,self.expiry,'Tambahan',Z)
            pref=app.refresh_all('Dina Putri',Z,self.day.isoformat(),'7','id',str(med1))
            self.assertEqual(pref[16:20],['Panadol','500 mg',4,'Awal'])
            self.assertEqual(pref[10]['value'],str(med1))
            # Select another medicine; its values must be loaded, not blank.
            pref2=app.refresh_all('Dina Putri',Z,self.day.isoformat(),'7','id',str(med2))
            self.assertEqual(pref2[16:20],['Vitamin','20 mg',3,'Tambahan'])
            self.assertEqual(pref2[10]['value'],str(med2))
            result=app.update_med(str(med1), 'Panadol Extra', '500 mg', 5, 'Updated', 'id')
            self.assertIn('diperbarui',result)
            self.assertEqual(db.one('SELECT name,low_stock FROM medicines WHERE id=?',(med1,))['name'],'Panadol Extra')

    def test_recent_history_orders_by_actual_recorded_instant(self):
        mid=db.add_medicine('Obat C','Tablet','',10,2,self.expiry,'',Z)
        start=self.start
        db.add_daily_plan(mid,1,2,['08:00','20:00'],start,'',Z)
        schedules=db.schedule_list()
        morning=next(x['id'] for x in schedules if x['at_time']=='08:00')
        evening=next(x['id'] for x in schedules if x['at_time']=='20:00')
        db.record_intake(morning,self.day,'taken',Z)
        db.record_intake(evening,self.day,'skipped',Z)
        with db.connect() as conn:
            conn.execute('UPDATE intake_logs SET recorded_at=? WHERE schedule_id=?',('2026-11-16T14:00:00+09:00',morning))
            conn.execute('UPDATE intake_logs SET recorded_at=? WHERE schedule_id=?',('2026-11-16T13:30:00+07:00',evening))
        # 13:30 +07 is 06:30 UTC, later than 14:00 +09 (=05:00 UTC).
        self.assertEqual(db.log_history()[0]['at_time'],'20:00')

    def test_history_displays_selected_local_timezone(self):
        import app
        from medimate_core import local_recorded_time
        stamp='2026-11-16T14:54:39+07:00'
        self.assertEqual(local_recorded_time(stamp, 'Asia/Jakarta'), '16/11/2026 14:54 WIB')
        self.assertEqual(local_recorded_time(stamp, 'Asia/Makassar'), '16/11/2026 15:54 WITA')
        self.assertEqual(local_recorded_time(stamp, 'Asia/Jayapura'), '16/11/2026 16:54 WIT')
        self.assertEqual(local_recorded_time('2026-11-16T23:30:00+07:00', 'Asia/Jayapura'), '17/11/2026 01:30 WIT')
        self.assertEqual(local_recorded_time('2026-11-16T14:54:39','Asia/Jayapura'),'16/11/2026 14:54')
        with db.use_profile('Dina Putri'):
            db.initialize()
            mid=db.add_medicine('Panadol','Tablet','',10,2,self.expiry,'',Z)
            db.add_schedule(mid,'08:00',2,self.start,'',Z)
            sid=db.schedule_list()[0]['id']
            db.record_intake(sid,self.day,'taken',Z)
            with db.connect() as conn:
                conn.execute('UPDATE intake_logs SET recorded_at=?',(stamp,))
            t_jakarta=app.format_logs('Asia/Jakarta','id').iloc[0]['Tercatat pada']
            t_makassar=app.format_logs('Asia/Makassar','id').iloc[0]['Tercatat pada']
            t_jayapura=app.format_logs('Asia/Jayapura','id').iloc[0]['Tercatat pada']
            self.assertEqual(t_jakarta, '16/11/2026 14:54 WIB')
            self.assertEqual(t_makassar, '16/11/2026 15:54 WITA')
            self.assertEqual(t_jayapura, '16/11/2026 16:54 WIT')
