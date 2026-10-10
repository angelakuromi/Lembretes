import os
import json
import time
from datetime import datetime, timedelta

from jnius import autoclass, cast

BASE = os.environ.get('ANDROID_PRIVATE', '.')
RFILE = os.path.join(BASE, 'lembretes.json')    # escrito pelo app
FFILE = os.path.join(BASE, 'disparados.json')   # escrito só por este serviço
CFG = os.path.join(BASE, 'config.json')         # nomes (a IA e você)
AFILE = os.path.join(BASE, 'confirmados.txt')   # escrito pela tela "Entendi"
CANAL = 'jane_lembretes'
REPETICOES = 3          # quantas vezes avisa se você não confirmar
INTERVALO = 10 * 60     # segundos entre uma repetição e outra


def carregar(caminho, padrao):
    try:
        with open(caminho, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return padrao


def salvar(caminho, dados):
    tmp = caminho + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(dados, f)
    os.replace(tmp, caminho)


def confirmados():
    # lê quais lembretes você já confirmou: {id: horário confirmado}
    d = {}
    try:
        with open(AFILE, encoding='utf-8') as f:
            for linha in f:
                if '|' not in linha:
                    continue
                i, o = linha.strip().split('|', 1)
                try:
                    d[i] = max(d.get(i, 0), int(o))
                except ValueError:
                    pass
    except Exception:
        pass
    return d


try:
    os.environ['TZ'] = autoclass('java.util.TimeZone').getDefault().getID()
    time.tzset()
except Exception as e:
    print('fuso:', e)

PythonService = autoclass('org.kivy.android.PythonService')
Context = autoclass('android.content.Context')
Builder = autoclass('android.app.Notification$Builder')
PendingIntent = autoclass('android.app.PendingIntent')
Intent = autoclass('android.content.Intent')
SDK = autoclass('android.os.Build$VERSION').SDK_INT


def notificar(texto, rid, occ, nid):
    ctx = PythonService.mService
    cfg = carregar(CFG, {})
    ia = cfg.get('ia') or 'Jane'
    eu = cfg.get('eu') or 'Angela'
    nm = cast('android.app.NotificationManager',
              ctx.getSystemService(Context.NOTIFICATION_SERVICE))

    if SDK >= 26:
        Canal = autoclass('android.app.NotificationChannel')
        canal = Canal(CANAL, 'Lembretes da ' + ia, 4)   # 4 = acende a tela, mas sem som
        canal.setSound(None, None)
        canal.enableVibration(False)
        canal.enableLights(False)
        canal.setLockscreenVisibility(1)
        nm.createNotificationChannel(canal)
        b = Builder(ctx, CANAL)
    else:
        b = Builder(ctx)

    # Tela de lembrete (Java), com o botão "Entendi"
    pacote = ctx.getPackageName()
    intent = Intent()
    intent.setClassName(pacote, pacote + '.AlarmeActivity')
    intent.setFlags(268435456 | 134217728 | 8388608)  # NEW_TASK | MULTIPLE_TASK | EXCLUDE_FROM_RECENTS
    intent.putExtra('rid', rid)
    intent.putExtra('occ', str(occ))
    intent.putExtra('texto', texto)
    intent.putExtra('ia', ia)
    intent.putExtra('eu', eu)
    intent.putExtra('nid', str(nid))
    intent.putExtra('afile', AFILE)
    pi = PendingIntent.getActivity(ctx, nid, intent, 67108864 | 134217728)  # IMMUTABLE | UPDATE_CURRENT

    b.setContentTitle(ia)
    b.setContentText('{}, é hora de: {}'.format(eu, texto))
    b.setSmallIcon(ctx.getApplicationInfo().icon)
    b.setAutoCancel(True)
    b.setContentIntent(pi)
    b.setFullScreenIntent(pi, True)    # acende a tela e abre a tela de lembrete
    b.setCategory('reminder')
    b.setVisibility(1)
    nm.notify(nid, b.build())


def ultima_ocorrencia(r, agora):
    # Último horário (já passado) em que um lembrete fixo deveria ter avisado.
    d = datetime.fromtimestamp(agora)
    for k in range(8):
        dia = (d - timedelta(days=k)).date()
        if dia.weekday() in r['dias']:
            occ = datetime(dia.year, dia.month, dia.day, r['h'], r['m'])
            if occ <= d:
                return occ.timestamp()
    return None


def main():
    try:
        PythonService.mService.setAutoRestartService(True)
    except Exception as e:
        print('autorestart:', e)

    while True:
        agora = time.time()
        rems = carregar(RFILE, [])
        feitos = carregar(FFILE, {})
        if not isinstance(feitos, dict):          # formato antigo
            feitos = {i: agora for i in feitos}
        acks = confirmados()
        mudou = False

        for r in rems:
            rid = r['id']
            nid = int(rid[:7], 16)
            if r.get('dias') is not None:
                # lembrete fixo: repete nos dias da semana escolhidos
                occ = ultima_ocorrencia(r, agora)
                if occ is None or occ <= r.get('criado', 0):
                    continue
                limite = 3 * 3600
            else:
                if r['quando'] > agora:
                    continue
                occ = r['quando']
                limite = 12 * 3600
            occ = int(occ)

            if acks.get(rid, 0) >= occ:      # você já confirmou
                continue
            est = feitos.get(rid)
            if isinstance(est, (int, float)):  # formato antigo (já avisado)
                est = {'occ': occ if est >= occ else 0, 'n': REPETICOES, 'last': est}
            if not isinstance(est, dict) or est.get('occ') != occ:
                est = {'occ': occ, 'n': 0, 'last': 0}
            if est['n'] >= REPETICOES:
                if feitos.get(rid) != est:
                    feitos[rid] = est
                    mudou = True
                continue
            if est['n'] == 0 and agora - occ > limite:
                est['n'] = REPETICOES        # passou tempo demais (celular desligado): não avisa
                feitos[rid] = est
                mudou = True
                continue
            if est['n'] == 0 or agora - est['last'] >= INTERVALO:
                try:
                    notificar(r['texto'], rid, occ, nid)
                except Exception as e:
                    print('notificar:', e)
                est['n'] += 1
                est['last'] = agora
                feitos[rid] = est
                mudou = True

        ids = set(r['id'] for r in rems)
        limpos = {i: v for i, v in feitos.items() if i in ids}
        if mudou or len(limpos) != len(feitos):
            salvar(FFILE, limpos)
        time.sleep(10)


main()
