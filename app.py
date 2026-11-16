"""MediMate — bilingual personal medicine organizer.

Launch locally: python app.py. Colab: Launch_App.ipynb.
"""
from __future__ import annotations

from datetime import timedelta
import html
import os

import gradio as gr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

import database as db
from medimate_core import ValidationError, local_today, parse_date, recording_rate, local_recorded_time

ZONE_DEFAULT = 'Asia/Jakarta'
ZONE_CHOICES = [('WIB · UTC+7', 'Asia/Jakarta'), ('WITA · UTC+8', 'Asia/Makassar'), ('WIT · UTC+9', 'Asia/Jayapura')]
DAILY_FREQUENCIES = [(f'{i} kali / {i} times', str(i)) for i in range(1, 7)]
DEFAULT_CLOCKS = ('08:00', '20:00', '12:00', '16:00', '18:00', '22:00')

# All static interface elements are registered for the top-right language toggle.
TRANSLATABLES: list[tuple] = []

def bi(id_text: str, en_text: str, language: str) -> str:
    return en_text if language == 'en' else id_text


def text_component(kind, id_text, en_text, **kwargs):
    cls = {'md': gr.Markdown, 'button': gr.Button}.get(kind)
    if cls is None:
        raise ValueError(kind)
    obj = cls(value=id_text, **kwargs) if kind == 'md' else cls(value=id_text, **kwargs)
    TRANSLATABLES.append((obj, 'value', id_text, en_text))
    return obj


def field(cls, id_label, en_label, **kwargs):
    obj = cls(label=id_label, **kwargs)
    TRANSLATABLES.append((obj, 'label', id_label, en_label))
    return obj


def page(id_title, en_title):
    obj = gr.Tab(id_title)
    TRANSLATABLES.append((obj, 'label', id_title, en_title))
    return obj


def translation_values(language):
    return [gr.update(**{prop: en if language == 'en' else ind})
            for _, prop, ind, en in TRANSLATABLES]


COLUMNS = {
    'med': (['ID','Nama obat','Bentuk','Kekuatan label','Stok layak pakai','Total stok','Stok kedaluwarsa','Batas rendah','Status','Catatan'],
            ['ID','Medicine','Form','Label strength','Usable stock','Total stock','Expired stock','Low threshold','Status','Notes']),
    'schedule': (['ID','Obat','Jam','Jumlah/konsumsi','Tanggal mulai','Tanggal akhir','Status'],
                 ['ID','Medicine','Time','Units/intake','Start date','End date','Status']),
    'events': (['Jam','Obat','Jumlah','Status','Stok dikurangi','Keterangan'],
               ['Time','Medicine','Quantity','Status','Stock deducted','Note']),
    'batches': (['Batch ID','Obat','Stok','Satuan','Kedaluwarsa','Status'],
                ['Batch ID','Medicine','Stock','Unit','Expiry','Status']),
    'logs': (['Tanggal','Jam','Obat','Status','Jumlah','Stok dikurangi','Tercatat pada','Keterangan'],
             ['Date','Time','Medicine','Status','Quantity','Stock deducted','Recorded at','Note']),
}
STATUS = {'id': {'taken': 'Diminum', 'skipped': 'Dilewati', 'unrecorded': 'Belum dicatat'},
          'en': {'taken': 'Taken', 'skipped': 'Skipped', 'unrecorded': 'Not recorded'}}
BATCH_STATUS = {'Kedaluwarsa': 'Expired', 'Mendekati kedaluwarsa': 'Expiring soon', 'Baik': 'Good'}


def cols(key, lang):
    return COLUMNS[key][lang == 'en']


def as_df(records, key, lang):
    return pd.DataFrame(records, columns=cols(key,lang))


def label_status(status, lang):
    return STATUS[lang].get(status, status)


def choices_meds(active=False, lang='id'):
    return [(f"{m['name']} · #{m['id']}" + (bi(' (nonaktif)',' (inactive)',lang) if not m['active'] else ''), str(m['id']))
            for m in db.medicine_list(active)]


def choices_schedules(lang='id'):
    return [(f"#{s['id']} · {s['medicine']} · {s['at_time']}" + (bi(' (arsip)',' (archived)',lang) if s['archived_on'] else ''), str(s['id']))
            for s in db.schedule_list()]


def choices_events(day, lang='id'):
    try:
        return [(f"{e['at_time']} · {e['medicine']} ({e['qty']} {e['unit']}) · {label_status(e['status'],lang)}", str(e['schedule_id']))
                for e in db.day_events(parse_date(day))]
    except ValidationError:
        return []


def format_meds(zone,lang):
    snap={m['id']:m for m in db.stock_snapshot(local_today(zone))}
    output=[]
    for m in db.medicine_list():
        x=snap.get(m['id'],{})
        status = (bi('Nonaktif','Inactive',lang) if not m['active'] else
                  bi('Stok rendah','Low stock',lang) if x.get('low') else bi('Aktif','Active',lang))
        output.append([m['id'],m['name'],m['form'],m['strength'],x.get('stock_usable','—'),
                       x.get('stock_total','—'),x.get('stock_expired','—'),m['low_stock'],status,m['notes']])
    return as_df(output,'med',lang)


def format_schedules(lang):
    output=[]
    for s in db.schedule_list():
        status=(bi('Diarsipkan','Archived',lang) if s['archived_on'] else
                bi('Obat nonaktif','Medicine inactive',lang) if not s['medicine_active'] else bi('Aktif','Active',lang))
        output.append([s['id'],s['medicine'],s['at_time'],f"{s['qty_per_intake']} {s['unit']}",
                       s['start_date'],s['end_date'] or bi('Berulang','Ongoing',lang),status])
    return as_df(output,'schedule',lang)


def format_events(day,lang):
    return as_df([[e['at_time'],e['medicine'],f"{e['qty']} {e['unit']}",label_status(e['status'],lang),e['deducted'],e['warning']]
                  for e in db.day_events(day)],'events',lang)


def format_batches(zone,lang):
    return as_df([[x['id'],x['medicine'],x['qty'],x['unit'],x['expiry'],
                   BATCH_STATUS.get(x['status'],x['status']) if lang=='en' else x['status']]
                  for x in db.batch_list(local_today(zone))],'batches',lang)


def format_logs(zone, lang):
    """Show the actual recording time in the currently selected Indonesian time zone."""
    return as_df([[r['scheduled_date'],r['at_time'],r['medicine'],label_status(r['status'],lang),
                   r['quantity'],r['stock_deducted'],local_recorded_time(r['recorded_at'],zone),r['warning']]
                  for r in db.log_history()],'logs',lang)


def dashboard_cards(zone,lang):
    day=local_today(zone)
    events=db.day_events(day)
    meds=db.stock_snapshot(day)
    metrics=[('💊',bi('OBAT AKTIF','ACTIVE MEDICINES',lang),str(len(meds)),'rose'),
             ('🗓️',bi('JADWAL HARI INI','TODAY\'S SCHEDULES',lang),str(len(events)),'lavender'),
             ('✨',bi('TERCATAT DIMINUM','REPORTED TAKEN',lang),str(sum(x['status']=='taken' for x in events)),'mint'),
             ('📦',bi('STOK RENDAH','LOW STOCK',lang),str(sum(bool(x['low']) for x in meds)),'peach')]
    cards=''.join(f'<div class="mm-metric {cl}"><span class="mm-metric-ico">{ico}</span><span class="mm-metric-label">{lab}</span><strong>{n}</strong></div>'
                  for ico,lab,n,cl in metrics)
    hint=bi('Ringkasan berdasarkan tanggal setempat','Summary based on local date',lang)
    return f'<div class="mm-grid">{cards}</div><div class="mm-subtle">{hint}: {day} · {html.escape(zone)}</div>'


def alerts_md(zone,lang):
    day=local_today(zone)
    lines=[]
    for m in db.stock_snapshot(day):
        n=html.escape(m['name'])
        if m['low']:
            lines.append(bi(f"- 📦 **{n}** — stok layak pakai tinggal **{m['stock_usable']} {m['unit']}** (batas {m['low_stock']}).",
                            f"- 📦 **{n}** — **{m['stock_usable']} {m['unit']}** usable units left (threshold {m['low_stock']}).",lang))
        if m['stock_expired']:
            lines.append(bi(f"- ⛔ **{n}** — terdapat **{m['stock_expired']} {m['unit']}** kedaluwarsa; tidak dihitung sebagai stok layak pakai.",
                            f"- ⛔ **{n}** — **{m['stock_expired']} {m['unit']}** expired units excluded from usable stock.",lang))
    for batch in db.batch_list(day):
        if batch['qty'] and batch['status']=='Mendekati kedaluwarsa':
            lines.append(bi(f"- ⚠️ **{html.escape(batch['medicine'])}**, batch #{batch['id']} — kedaluwarsa **{batch['expiry']}**.",
                            f"- ⚠️ **{html.escape(batch['medicine'])}**, batch #{batch['id']} — expires **{batch['expiry']}**.",lang))
    return '\n'.join(lines) if lines else bi('🌷 Tidak ada peringatan stok atau kedaluwarsa saat ini.',
                                             '🌷 No low-stock or expiry alerts right now.',lang)


def analysis_plot(events,lang):
    values=[sum(x['status']==s for x in events) for s in ('taken','skipped','unrecorded')]
    names=[label_status(s,lang) for s in ('taken','skipped','unrecorded')]
    fig,ax=plt.subplots(figsize=(7.6,3.5))
    fig.patch.set_facecolor('#FFFCFD')
    ax.set_facecolor('#FFFCFD')
    bars=ax.bar(names,values,color=['#84CDB6','#FDBF99','#C8B9EA'],width=0.52)
    ax.set_ylabel(bi('Jumlah kejadian','Scheduled events',lang),color='#695B72')
    ax.set_ylim(0,max(1,max(values))*1.28)
    ax.spines[['top','right','left']].set_visible(False)
    ax.spines['bottom'].set_color('#EADCE8')
    ax.tick_params(axis='both',colors='#695B72',length=0)
    ax.yaxis.grid(True,alpha=.14)
    ax.set_axisbelow(True)
    ax.bar_label(bars,padding=5,fontsize=11,color='#695B72')
    fig.tight_layout()
    return fig


def analytics_content(zone,period,lang):
    end=local_today(zone)
    start=end-timedelta(days=int(period)-1)
    events=db.analytics_events(start,end,zone)
    taken=sum(x['status']=='taken' for x in events)
    skipped=sum(x['status']=='skipped' for x in events)
    unrecorded=len(events)-taken-skipped
    rate=recording_rate(taken,len(events))
    summary=bi(f"**{start} – {end}** · Jadwal yang sudah berlalu: **{len(events)}** · Diminum: **{taken}** · Dilewati: **{skipped}** · Belum dicatat: **{unrecorded}** · Persentase diminum: **{rate:.1f}%**.",
               f"**{start} – {end}** · Past scheduled events: **{len(events)}** · Taken: **{taken}** · Skipped: **{skipped}** · Not recorded: **{unrecorded}** · Recorded as taken: **{rate:.1f}%**.",lang)
    return summary,analysis_plot(events,lang)


def scoped(f):
    def run(profile,*args):
        if not profile:
            raise gr.Error('Masukkan nama lengkap / Enter your full name first.')
        with db.use_profile(profile):
            return f(*args)
    run.__name__ = "profile_" + getattr(f,"__name__","operation")
    return run


def refresh_all(profile,zone,day,period,lang,selected_med=None):
    if not profile:
        return [gr.update() for _ in range(20)]
    with db.use_profile(profile):
        day=parse_date(day).isoformat()
        meds=db.medicine_list()
        count=len(meds)
        profile_label=f"🌷 <b>{html.escape(profile)}</b> · {count} "+bi("obat tersimpan","saved medicines",lang)
        summary,chart=analytics_content(zone,period,lang)
        options=choices_meds(False,lang)
        valid={value for _,value in options}
        selected_id=str(selected_med) if selected_med is not None else None
        if selected_id not in valid:
            selected_id=options[0][1] if options else None
        current_values=load_med(selected_id)
        return [dashboard_cards(zone,lang),format_events(local_today(zone),lang),alerts_md(zone,lang),
                format_meds(zone,lang),format_schedules(lang),format_events(day,lang),
                format_batches(zone,lang),format_logs(zone,lang),summary,chart,
                gr.update(choices=options,value=selected_id),gr.update(choices=choices_meds(True,lang)),
                gr.update(choices=choices_meds(True,lang)),gr.update(choices=choices_schedules(lang)),
                gr.update(choices=choices_events(day,lang)),profile_label,
                *current_values]


def call(f,*args):
    try:
        return f(*args)
    except ValidationError as e:
        raise gr.Error(str(e)) from e
    except (ValueError,TypeError) as e:
        raise gr.Error('Input tidak sesuai / Invalid input.') from e


def visible_daily_times(frequency):
    count = int(frequency)
    return [gr.update(visible=(i < count)) for i in range(len(DEFAULT_CLOCKS))]


def add_med(name, form, strength, qty, low, expiry, notes, zone, lang):
    mid = call(db.add_medicine, name, form, strength, qty, low, expiry, notes, zone)
    return bi(f'🌷 Obat #{mid} disimpan. Atur jumlah per minum, frekuensi, dan jam pada tab Jadwal.',
              f'🌷 Medicine #{mid} saved. Set units, frequency, and times in the Schedule tab.', lang)


def update_med(mid,name,strength,low,notes,lang):
    call(db.update_medicine,mid,name,strength,low,notes)
    return bi('✨ Informasi obat diperbarui.','✨ Medicine updated.',lang)


def toggle_med(mid,active,confirmed,lang):
    if not active and not confirmed:
        raise gr.Error(bi('Centang konfirmasi terlebih dahulu.','Please confirm first.',lang))
    call(db.set_medicine_active,mid,active)
    return bi('✨ Status obat diperbarui.','✨ Medicine status updated.',lang)


def load_med(mid):
    if not mid:
        return '','',0,''
    r=db.one('SELECT * FROM medicines WHERE id=?',(int(mid),))
    return (r['name'],r['strength'],r['low_stock'],r['notes']) if r else ('','',0,'')


def add_schedule(mid, qty, freq, *times_start_end_zone_lang):
    *times, start, end, zone, lang = times_start_end_zone_lang
    count = call(db.add_daily_plan, mid, qty, freq, times, start, end, zone)
    return bi(f'🗓️ {count} jadwal harian disimpan secara terpisah.',
              f'🗓️ {count} independent daily intake times saved.', lang)


def update_schedule(sid,mid,clock,qty,start,end,lang):
    call(db.update_schedule,sid,mid,clock,qty,start,end)
    return bi('✨ Jadwal diperbarui.','✨ Schedule updated.',lang)


def load_schedule(sid):
    if not sid:
        return gr.update(),'08:00',1,'',''
    s=db.one('SELECT * FROM schedules WHERE id=?',(int(sid),))
    return (gr.update(value=str(s['medicine_id'])),s['at_time'],s['qty_per_intake'],s['start_date'],s['end_date'] or '') if s else (gr.update(),'08:00',1,'','')


def archive_schedule(sid,zone,confirmed,lang):
    if not confirmed:
        raise gr.Error(bi('Centang konfirmasi arsip.','Please confirm archiving.',lang))
    call(db.archive_schedule,sid,zone)
    return bi('📁 Jadwal diarsipkan.','📁 Schedule archived.',lang)


def take(sid,day,status,zone,lang):
    result=call(db.record_intake,sid,day,status,zone)
    if lang=='id':
        return result
    if 'sudah tercatat' in result:
        return 'Already recorded — stock was not deducted again.'
    if status=='clear':
        return 'Entry cleared; previous stock movement reversed.'
    if status=='skipped':
        return 'Skipped status saved; stock unchanged.'
    if 'tanpa pengurangan' in result:
        return 'Recorded as taken; not enough usable stock, so no stock was deducted. Please reconcile your inventory records.'
    return 'Taken status saved; stock deducted once.'


def refill(mid,qty,expiry,zone,lang):
    call(db.add_batch,mid,qty,expiry,zone)
    return bi('📦 Stok baru disimpan.','📦 New stock saved.',lang)


def export_backup(lang):
    return db.export_database(),bi('⬇️ Backup siap diunduh.','⬇️ Backup is ready to download.',lang)


def import_backup(path,confirm,lang):
    call(db.import_database,path,confirm)
    return bi('✨ Backup berhasil dipulihkan.','✨ Backup restored.',lang)


def enter_profile(raw,zone,lang):
    name=call(db.display_name,raw)
    with db.use_profile(name):
        db.initialize()
        meds=len(db.medicine_list())
    heading=f'🌷 <b>{html.escape(name)}</b> · {meds} '+bi('obat tersimpan','saved medicines',lang)
    return name,gr.update(visible=False),gr.update(visible=True),heading


def leave_profile():
    return '',gr.update(visible=True),gr.update(visible=False),''


CSS=r"""
/* MediMate — strawberry cream / high-contrast light interface */
:root {
  color-scheme: light;
  --mm-ink:#39273F; --mm-muted:#66546E; --mm-pink:#DD1777;
  --mm-pink-deep:#AD0E59; --mm-blush:#FFF1F7; --mm-border:#E6D4E0;
}
html,body,gradio-app {background:#FFF8FC!important;color:var(--mm-ink)!important;}
.gradio-container,.dark .gradio-container,.gradio-container.dark {
  color-scheme:light!important;
  --body-background-fill:#FFF8FC!important;
  --body-text-color:#39273F!important;
  --body-text-color-subdued:#66546E!important;
  --block-background-fill:#FFFFFF!important;
  --block-label-background-fill:#FFF1F7!important;
  --block-label-text-color:#6D3158!important;
  --block-title-text-color:#39273F!important;
  --input-background-fill:#FFFFFF!important;
  --input-background-fill-focus:#FFF5FA!important;
  --input-border-color:#D9B9CE!important;
  --color-accent:#DD1777!important;
  --color-accent-soft:#FFE4F0!important;
  --background-fill-primary:#FFFFFF!important;
  --background-fill-secondary:#FFF4F9!important;
  --button-primary-background-fill:#DD1777!important;
  --button-secondary-background-fill:#DD1777!important;
  --button-secondary-text-color:#FFFFFF!important;
  max-width:1060px!important;margin:0 auto!important;
  padding:18px 28px 64px!important;background:transparent!important;
  color:var(--mm-ink)!important;font-family:ui-rounded,'Segoe UI',Arial,sans-serif!important;
}
#mm-shell {margin:0 auto!important;}
#mm-topbar {background:#FFFFFF!important;border:1px solid #F0D9E5!important;border-radius:24px!important;box-shadow:0 9px 34px #E9C9DB40!important;padding:12px 20px!important;margin:9px 0 20px!important;align-items:center!important;}
.mm-brand {display:flex;align-items:center;gap:11px;font-size:21px;font-weight:850;letter-spacing:-.5px;color:#613253;}
.mm-logo {display:grid;place-items:center;width:41px;height:41px;background:#FAD3E4;border-radius:15px;font-size:21px;box-shadow:inset 0 -3px #EFADCB;}
#mm-lang {max-width:205px!important;margin-left:auto!important;min-width:165px!important;}
#mm-lang .wrap {display:flex!important;justify-content:flex-end!important;align-items:center!important;gap:5px!important;background:#FFF0F6!important;padding:6px!important;border:1px solid #F1D0E0!important;border-radius:999px!important;}
#mm-lang .wrap label {border-radius:999px!important;padding:6px 10px!important;font-size:12px!important;font-weight:800!important;color:#713A60!important;white-space:nowrap!important;cursor:pointer!important;transition:background .2s ease,color .2s ease!important;}
#mm-lang .wrap label:hover {background:#FFE0ED!important;color:#9F1259!important;}
#mm-lang .wrap label:has(input:checked) {background:#D91C75!important;color:#FFFFFF!important;box-shadow:0 3px 12px #D91C7540!important;}
#mm-lang input[type=radio] {accent-color:#D91C75!important;}
#mm-login {max-width:660px!important;margin:54px auto 76px!important;padding:35px!important;border:1px solid #EBD3E2!important;background:#FFFFFF!important;border-radius:28px!important;box-shadow:0 20px 60px #E5BBD83A!important;}
#mm-login h2 {text-align:center!important;color:#55315D!important;font-size:29px!important;}
#mm-login p {text-align:center!important;color:#5C4664!important;}
#mm-hero {border-radius:26px!important;padding:26px 30px!important;margin:0 0 14px!important;background:linear-gradient(105deg,#FFD8E7 0%,#EDE0FF 48%,#FFF0D8 100%)!important;border:1px solid #F1D4E4!important;}
#mm-hero h1 {font-size:37px!important;font-weight:850!important;letter-spacing:-1.3px!important;color:#59365C!important;margin:0 0 4px!important;}
#mm-hero p {color:#4E3B56!important;font-size:14px!important;line-height:1.65!important;margin:0!important;max-width:670px;}
.mm-kicker {display:block;color:#8D3C70!important;font-size:11px!important;letter-spacing:2.1px!important;font-weight:850!important;margin-bottom:10px!important;}
.mm-profile {font-size:13px!important;color:#684467!important;margin:9px 0!important;}
.mm-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:12px 0 14px;}
.mm-metric {position:relative;border:1px solid #E9D7E4;border-radius:21px;padding:19px;min-height:130px;display:flex;flex-direction:column;align-items:flex-start;gap:5px;box-shadow:0 7px 20px #E3C5DA36;}
.mm-metric.rose {background:#FFE2EE}.mm-metric.lavender {background:#EAE0FF}.mm-metric.mint {background:#DBF5E9}.mm-metric.peach {background:#FFEBD6}
.mm-metric-ico {font-size:23px!important}.mm-metric-label {font-size:10px!important;font-weight:850!important;letter-spacing:.65px!important;color:#563C60!important;}
.mm-metric strong {font-size:32px!important;color:#422C4B!important;line-height:1.1!important;}
.mm-subtle {font-size:12px!important;color:#69536F!important;margin:3px 0 18px!important;}
/* Consistent readable surfaces even when browser OS is in dark mode. */
#mm-workspace .block:not(.html):not(.markdown),
#mm-login .block:not(.html):not(.markdown) {background:#FFFFFF!important;border-color:#E6CFE0!important;border-radius:15px!important;}
#mm-workspace .form,#mm-workspace .wrap:has(>input),#mm-workspace .wrap:has(>textarea),
#mm-login .form,#mm-login .wrap:has(>input) {background:#FFFFFF!important;}
.gradio-container input:not([type=checkbox]):not([type=radio]),
.gradio-container textarea,.gradio-container select,
.gradio-container [role=combobox],
.gradio-container .wrap input:not([type=checkbox]):not([type=radio]) {
  background:#FFFFFF!important;color:#3A2940!important;-webkit-text-fill-color:#3A2940!important;
  border-color:#DEBDD1!important;caret-color:#C41168!important;
}
.gradio-container input::placeholder,.gradio-container textarea::placeholder {color:#87738B!important;opacity:1!important;}
.gradio-container input:focus,.gradio-container textarea:focus,.gradio-container [role=combobox]:focus-within {border-color:#DD1777!important;box-shadow:0 0 0 3px #F8C4DC80!important;}
.gradio-container .prose,.gradio-container .prose p,.gradio-container .markdown p,
.gradio-container label,.gradio-container .label-wrap,.gradio-container .label-wrap span,
.gradio-container .block-title,.gradio-container .block-label {color:#4C3454!important;}
#mm-workspace .prose h2,#mm-workspace .prose h3,#mm-workspace .prose h4 {color:#4F3056!important;font-weight:850!important;}
#mm-workspace .prose {color:#4F3B57!important;}
/* Strong pink buttons with soft ivory-pink hover. */
#mm-workspace button.primary,#mm-workspace button.secondary,
#mm-login button.primary,#mm-login button.secondary {
  background:#DD1777!important;border:1px solid #DD1777!important;
  color:#FFFFFF!important;box-shadow:0 5px 14px #D91B7540!important;
  border-radius:14px!important;font-weight:800!important;
  transition:background-color .22s ease,color .22s ease,border-color .22s ease,
             box-shadow .22s ease,transform .22s ease!important;
}
#mm-workspace button.primary:hover,#mm-workspace button.secondary:hover,
#mm-login button.primary:hover,#mm-login button.secondary:hover {
  background:#FFF4F9!important;border-color:#DC237C!important;color:#AD0E59!important;
  box-shadow:0 6px 16px #D91B7522!important;transform:translateY(-2px)!important;
}
#mm-workspace button.primary:active,#mm-workspace button.secondary:active,
#mm-login button.primary:active,#mm-login button.secondary:active {transform:translateY(0)!important;background:#FFE5EF!important;}
#mm-workspace button.primary:focus-visible,#mm-workspace button.secondary:focus-visible,
#mm-login button.primary:focus-visible {outline:3px solid #F5A5C8!important;outline-offset:3px!important;}
#mm-workspace button[role=tab] {border-radius:12px!important;border:1px solid transparent!important;color:#624363!important;font-weight:750!important;font-size:12px!important;padding:10px 13px!important;background:transparent!important;transition:all .2s ease!important;}
#mm-workspace button[role=tab]:hover {background:#FFD7E9!important;color:#A31462!important;transform:translateY(-1px)!important;}
#mm-workspace button[role=tab][aria-selected=true] {background:#DA2077!important;color:#FFFFFF!important;border-color:#C9156C!important;box-shadow:0 5px 14px #D91B7535!important;}
#mm-workspace button[role=tab][aria-selected=true]:hover {background:#BC115F!important;color:#FFFFFF!important;}
#mm-workspace .tabs > .tab-nav {margin:14px 0 21px!important;gap:6px!important;background:#F8EAF3!important;border-radius:17px!important;padding:7px!important;border:1px solid #E7D5E6!important;flex-wrap:wrap!important;}
#mm-workspace .tabitem {background:transparent!important;}
/* Clear table text and headings; no pale text on a pale background. */
.gradio-container table,.gradio-container .table-wrap,.gradio-container thead,.gradio-container tbody,
.gradio-container td,.gradio-container th {color:#37273D!important;border-color:#E7D8E3!important;}
.gradio-container th {background:#F9E5F0!important;color:#5D2F55!important;font-weight:800!important;}
.gradio-container td {background:#FFFFFF!important;color:#3D2C45!important;}
.gradio-container tr:hover td {background:#FFF0F7!important;}
.gradio-container .message,.gradio-container .info,.gradio-container .prose small {color:#513956!important;}
footer,.gradio-footer,.built-with-gradio {display:none!important;}
@media(max-width:780px) {
  .gradio-container {padding:10px 12px 40px!important;}
  #mm-login {padding:22px!important;margin:24px auto!important;}
  .mm-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
  .mm-metric {min-height:104px;padding:13px;}
  .mm-metric strong {font-size:25px!important;}
  #mm-hero {padding:22px 18px!important;}
  #mm-hero h1 {font-size:30px!important;}
}
"""

THEME = gr.themes.Soft(primary_hue='pink',secondary_hue='purple',neutral_hue='slate',radius_size='lg')


def build_app():
    TRANSLATABLES.clear()
    today=local_today(ZONE_DEFAULT).isoformat()
    with gr.Blocks(title='MediMate · Your medicine companion',analytics_enabled=False) as ui:
        with gr.Column(elem_id='mm-shell'):
            with gr.Row(elem_id='mm-topbar'):
                with gr.Column(scale=4,min_width=150):
                    gr.HTML('<div class="mm-brand"><span class="mm-logo">💊</span> MediMate</div>')
                with gr.Column(scale=1,min_width=174):
                    language=gr.Radio(choices=[('🇮🇩 ID','id'),('🇬🇧 EN','en')],value='id',show_label=False,container=False,elem_id='mm-lang')

            profile=gr.State('')
            with gr.Column(elem_id='mm-login') as login_panel:
                text_component('md','## Halo, selamat datang! 🌷\nMasukkan nama lengkap untuk membuka atau membuat catatan MediMate.',
                               '## Hey, welcome! 🌷\nEnter your full name to open or create your MediMate records.')
                username=field(gr.Textbox,'Nama Lengkap','Full Name',placeholder='-',max_lines=1)
                login_btn=text_component('button','Buka catatan saya  ✨','Open my records  ✨',variant='primary')

            with gr.Column(visible=False,elem_id='mm-workspace') as workspace:
                header=gr.HTML('''<div id="mm-hero"><span class="mm-kicker">YOUR EVERYDAY MEDICINE ORGANIZER</span>
                    <h1>MediMate <span style="color:#d88bad">✿</span></h1>
                    <p>Kelola obat, jadwal, stok, dan catatan konsumsi dengan lebih mudah — semuanya dalam satu tempat.</p></div>''')
                profile_header=gr.HTML(elem_classes=['mm-profile'])
                with gr.Row(equal_height=True):
                    zone=field(gr.Dropdown,'Zona waktu','Time zone',choices=ZONE_CHOICES,value=ZONE_DEFAULT,scale=2,min_width=160)
                    refresh_btn=text_component('button','↻ Perbarui','↻ Refresh',variant='secondary',scale=1,min_width=95)
                    logout_btn=text_component('button','Ganti nama','Change name',variant='secondary',scale=1,min_width=135)
                with gr.Tabs():
                    with page('🏠 Beranda','🏠 Dashboard'):
                        cards=gr.HTML()
                        text_component('md','### 🌼 Jadwal hari ini','### 🌼 Today’s schedule')
                        today_table=gr.Dataframe(headers=cols('events','id'),interactive=False,wrap=True,show_label=False)
                        text_component('md','### 🍑 Peringatan stok & kedaluwarsa','### 🍑 Stock & expiry alerts')
                        alerts=gr.Markdown()

                    with page('💊 Obat saya','💊 My medicines'):
                        text_component('md','### Tambahkan obat\nSimpan informasi obat dan stok awal. Atur dosis serta waktu konsumsi melalui tab **Jadwal**.',
                                       '### Add a medicine\nSave medicine details and starting stock. Set dosage and intake times under **Schedule**.')
                        with gr.Row():
                            with gr.Column():
                                new_name=field(gr.Textbox,'Nama obat','Medicine name',placeholder='Nama obat')
                                new_form=field(gr.Dropdown,'Bentuk sediaan','Dosage form',choices=['Tablet','Kapsul'],value='Tablet')
                                new_strength=field(gr.Textbox,'Kekuatan pada label (opsional)','Strength on label (optional)')
                            with gr.Column():
                                new_qty=field(gr.Number,'Stok awal (unit)','Initial stock (units)',value=20,precision=0)
                                new_low=field(gr.Number,'Batas stok rendah','Low-stock threshold',value=5,precision=0)
                                new_exp=field(gr.Textbox,'Kedaluwarsa (YYYY-MM-DD)','Expiry (YYYY-MM-DD)',value=(local_today(ZONE_DEFAULT)+timedelta(days=180)).isoformat())
                        new_notes=field(gr.Textbox,'Catatan (opsional)','Notes (optional)',lines=2)
                        med_add=text_component('button','+ Tambah obat','+ Add medicine',variant='primary')
                        text_component('md','### Daftar obat','### Medicine list')
                        medicines_table=gr.Dataframe(headers=cols('med','id'),interactive=False,wrap=False,show_label=False)
                        text_component('md','### Edit atau nonaktifkan obat','### Edit or deactivate a medicine')
                        edit_med=field(gr.Dropdown,'Pilih obat','Select medicine',choices=[])
                        with gr.Row():
                            edit_name=field(gr.Textbox,'Nama obat','Medicine name')
                            edit_strength=field(gr.Textbox,'Kekuatan pada label','Strength on label')
                        edit_low=field(gr.Number,'Batas stok rendah','Low-stock threshold',value=5,precision=0)
                        edit_notes=field(gr.Textbox,'Catatan','Notes')
                        with gr.Row():
                            med_update=text_component('button','Simpan perubahan','Save changes',variant='primary')
                            med_activate=text_component('button','Aktifkan lagi','Reactivate')
                        med_confirm=field(gr.Checkbox,'Konfirmasi menonaktifkan obat','Confirm deactivation',value=False)
                        med_deactivate=text_component('button','Nonaktifkan obat','Deactivate medicine')
                        med_msg=gr.Textbox(show_label=False,interactive=False)

                    with page('🗓️ Jadwal','🗓️ Schedule'):
                        text_component('md','### Atur jadwal harian\nPilih obat, jumlah per kali minum, frekuensi per hari, dan jam masing-masing. Setiap jam menjadi satu catatan konsumsi yang dapat dikonfirmasi sendiri.',
                                       '### Daily intake plan\nChoose the medicine, units per intake, times per day, and every intake time. Each time becomes an independently tracked entry.')
                        sch_med=field(gr.Dropdown,'Obat','Medicine',choices=[])
                        with gr.Row():
                            sch_qty=field(gr.Number,'Jumlah per kali minum (unit)','Units per intake',value=1,precision=0)
                            sch_freq=field(gr.Dropdown,'Frekuensi per hari','Times per day',choices=DAILY_FREQUENCIES,value='2')
                        sch_clock_fields=[]
                        for first in range(0, 6, 2):
                            with gr.Row():
                                for i in range(first, first+2):
                                    sch_clock_fields.append(field(gr.Textbox,f'Jam minum ke-{i+1} (HH:MM)',f'Intake {i+1} time (HH:MM)',
                                                                  value=DEFAULT_CLOCKS[i],visible=(i<2)))
                        with gr.Row():
                            sch_start=field(gr.Textbox,'Tanggal mulai','Start date',value=today)
                            sch_end=field(gr.Textbox,'Tanggal akhir (opsional)','End date (optional)',placeholder='YYYY-MM-DD')
                        sch_add=text_component('button','+ Simpan seluruh jadwal','+ Save all intake times',variant='primary')
                        text_component('md','### Semua jadwal per kali minum','### Every intake time')
                        sch_table=gr.Dataframe(headers=cols('schedule','id'),interactive=False,wrap=True,show_label=False)
                        text_component('md','### Edit satu jadwal\nPerubahan pada satu jam tidak mengubah catatan jam yang lain.',
                                       '### Edit one intake time\nEditing one time does not change the other scheduled entries.')
                        sch_select=field(gr.Dropdown,'Pilih jadwal untuk diedit / diarsipkan','Choose intake time to edit / archive',choices=[])
                        with gr.Row():
                            sch_clock=field(gr.Textbox,'Jam terpilih (HH:MM)','Selected time (HH:MM)',value='08:00')
                            sch_edit_qty=field(gr.Number,'Unit per kali minum terpilih','Selected units per intake',value=1,precision=0)
                        with gr.Row():
                            sch_edit_start=field(gr.Textbox,'Tanggal mulai jadwal','Schedule start date',value=today)
                            sch_edit_end=field(gr.Textbox,'Tanggal akhir jadwal','Schedule end date',placeholder='YYYY-MM-DD')
                        sch_update=text_component('button','Simpan perubahan jadwal','Save schedule changes',variant='primary')
                        sch_confirm=field(gr.Checkbox,'Konfirmasi pengarsipan jadwal','Confirm archive',value=False)
                        sch_archive=text_component('button','Arsipkan jadwal','Archive schedule')
                        sch_msg=gr.Textbox(show_label=False,interactive=False)

                    with page('✅ Catatan konsumsi','✅ Intake tracker'):
                        text_component('md','### Konfirmasi tiap kali minum\nPilih tanggal dan jam obat. Setiap jam dikonfirmasi sendiri, bukan satu status untuk satu hari.',
                                       '### Confirm each intake separately\nChoose a date and one scheduled time. Each intake time has its own status.')
                        track_date=field(gr.Textbox,'Tanggal (YYYY-MM-DD)','Date (YYYY-MM-DD)',value=today)
                        track_select=field(gr.Dropdown,'Pilih jadwal konsumsi','Select scheduled intake',choices=[])
                        with gr.Row():
                            take_btn=text_component('button','✓ Diminum','✓ Taken',variant='primary')
                            skip_btn=text_component('button','✕ Dilewati','✕ Skipped')
                            undo_btn=text_component('button','↶ Batalkan','↶ Clear')
                        track_msg=gr.Textbox(show_label=False,interactive=False)
                        text_component('md','### Jadwal tanggal tersebut','### Events for selected day')
                        day_table=gr.Dataframe(headers=cols('events','id'),interactive=False,wrap=True,show_label=False)
                        text_component('md','### Riwayat terbaru','### Recent history')
                        history_table=gr.Dataframe(headers=cols('logs','id'),interactive=False,wrap=False,
                                                   column_widths=['105px','70px','135px','100px','78px','128px','185px','200px'],
                                                   show_label=False)

                    with page('📦 Persediaan','📦 Inventory'):
                        text_component('md','### Persediaan per batch\nPantau stok dan tanggal kedaluwarsa setiap batch.',
                                       '### Inventory by batch\nTrack quantities and expiry dates for each batch.')
                        batch_table=gr.Dataframe(headers=cols('batches','id'),interactive=False,wrap=True,show_label=False)
                        text_component('md','### Tambah stok baru','### Add a new batch')
                        stock_med=field(gr.Dropdown,'Obat','Medicine',choices=[])
                        with gr.Row():
                            stock_qty=field(gr.Number,'Jumlah baru (unit)','New quantity (units)',value=10,precision=0)
                            stock_exp=field(gr.Textbox,'Tanggal kedaluwarsa','Expiry date',value=(local_today(ZONE_DEFAULT)+timedelta(days=120)).isoformat())
                        stock_add=text_component('button','+ Simpan batch','+ Save batch',variant='primary')
                        stock_msg=gr.Textbox(show_label=False,interactive=False)

                    with page('📊 Analitik & backup','📊 Analytics & backup'):
                        text_component('md','### Ringkasan pencatatan',
                                       '### Recording overview')
                        period=field(gr.Dropdown,'Periode','Period',choices=[('7 hari / days','7'),('30 hari / days','30'),('90 hari / days','90')],value='7')
                        analysis_summary=gr.Markdown()
                        analysis_chart=gr.Plot(show_label=False)
                        text_component('md','### Simpan & pulihkan data\nEkspor atau impor database catatan.',
                                       '### Save & restore records\nExport or import your records database.')
                        backup_export=text_component('button','⬇ Unduh backup','⬇ Export backup',variant='primary')
                        backup_file=field(gr.File,'File backup','Backup file',interactive=False)
                        backup_import=field(gr.File,'Unggah backup SQLite','Upload SQLite backup',file_types=['.sqlite','.db'],type='filepath')
                        restore_text=field(gr.Textbox,'Ketik RESTORE untuk mengganti data','Type RESTORE to overwrite records')
                        backup_restore=text_component('button','Pulihkan backup','Restore backup')
                        backup_msg=gr.Textbox(show_label=False,interactive=False)

            # A profile name is passed explicitly to callbacks, isolating records by full-name key.
            outputs=[cards,today_table,alerts,medicines_table,sch_table,day_table,batch_table,
                     history_table,analysis_summary,analysis_chart,edit_med,sch_med,stock_med,sch_select,track_select,profile_header,
                     edit_name,edit_strength,edit_low,edit_notes]
            refresh_inputs=[profile,zone,track_date,period,language,edit_med]

            def wire(button,handler,inputs,result):
                button.click(scoped(handler),inputs=[profile]+inputs+[language],outputs=result).then(
                    refresh_all,inputs=refresh_inputs,outputs=outputs)

            # Entering a full name selects or creates the corresponding record database.
            for trigger,method in [(login_btn,'click'),(username,'submit')]:
                getattr(trigger,method)(enter_profile,inputs=[username,zone,language],outputs=[profile,login_panel,workspace,profile_header]).then(
                    refresh_all,inputs=refresh_inputs,outputs=outputs)
            logout_btn.click(leave_profile,outputs=[profile,login_panel,workspace,profile_header])

            language.change(translation_values,inputs=[language],outputs=[x[0] for x in TRANSLATABLES]).then(
                refresh_all,inputs=refresh_inputs,outputs=outputs)
            # Hero, tip and profile header use dynamically re-rendered bilingual content.
            def update_header(lang,p):
                desc=bi('Kelola obat, jadwal, stok, dan catatan konsumsi dengan lebih mudah — semuanya dalam satu tempat.',
                        'Keep your medicine schedules, inventory and intake history organised in one lovely place.',lang)
                hero=f'<div id="mm-hero"><span class="mm-kicker">YOUR EVERYDAY MEDICINE ORGANIZER</span><h1>MediMate <span style="color:#d88bad">✿</span></h1><p>{desc}</p></div>'
                return hero
            language.change(update_header,inputs=[language,profile],outputs=[header])

            for button in (refresh_btn,):
                button.click(refresh_all,inputs=refresh_inputs,outputs=outputs)
            zone.change(refresh_all,inputs=refresh_inputs,outputs=outputs)
            track_date.change(refresh_all,inputs=refresh_inputs,outputs=outputs)
            period.change(refresh_all,inputs=refresh_inputs,outputs=outputs)

            # Use user-only input to load selected medicine. Refresh independently prefills the first medicine.
            edit_med.input(scoped(load_med),inputs=[profile,edit_med],outputs=[edit_name,edit_strength,edit_low,edit_notes])
            sch_select.change(scoped(load_schedule),inputs=[profile,sch_select],outputs=[sch_med,sch_clock,sch_edit_qty,sch_edit_start,sch_edit_end])
            sch_freq.change(visible_daily_times, inputs=[sch_freq], outputs=sch_clock_fields)

            wire(med_add,add_med,[new_name,new_form,new_strength,new_qty,new_low,new_exp,new_notes,zone],med_msg)
            wire(med_update,update_med,[edit_med,edit_name,edit_strength,edit_low,edit_notes],med_msg)
            med_activate.click(scoped(lambda mid,lang:toggle_med(mid,True,True,lang)),inputs=[profile,edit_med,language],outputs=med_msg).then(refresh_all,inputs=refresh_inputs,outputs=outputs)
            wire(med_deactivate,lambda mid,confirmed,lang:toggle_med(mid,False,confirmed,lang),[edit_med,med_confirm],med_msg)
            wire(sch_add,add_schedule,[sch_med,sch_qty,sch_freq]+sch_clock_fields+[sch_start,sch_end,zone],sch_msg)
            wire(sch_update,update_schedule,[sch_select,sch_med,sch_clock,sch_edit_qty,sch_edit_start,sch_edit_end],sch_msg)
            wire(sch_archive,archive_schedule,[sch_select,zone,sch_confirm],sch_msg)
            for btn,status in ((take_btn,'taken'),(skip_btn,'skipped'),(undo_btn,'clear')):
                wire(btn,lambda sid,day,zone,lang,st=status:take(sid,day,st,zone,lang),[track_select,track_date,zone],track_msg)
            wire(stock_add,refill,[stock_med,stock_qty,stock_exp,zone],stock_msg)
            backup_export.click(scoped(export_backup),inputs=[profile,language],outputs=[backup_file,backup_msg])
            wire(backup_restore,import_backup,[backup_import,restore_text],backup_msg)
    return ui


medimate_app=build_app()

if __name__=='__main__':
    medimate_app.launch(share=False,inbrowser=True,server_name='127.0.0.1',inline=False,
                show_error=True,footer_links=[],theme=THEME,css=CSS)
