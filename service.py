import os
import json
import time

from jnius import autoclass, cast

BASE = os.environ.get('ANDROID_PRIVATE', '.')
RFILE = os.path.join(BASE, 'lembretes.json')    # escrito pelo app
FFILE = os.path.join(BASE, 'disparados.json')   # escrito só por este serviço
CANAL = 'lembretes_silenciosos'


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


PythonService = autoclass('org.kivy.android.PythonService')
Context = autoclass('android.content.Context')
Builder = autoclass('android.app.Notification$Builder')
PendingIntent = autoclass('android.app.PendingIntent')
SDK = autoclass('android.os.Build$VERSION').SDK_INT


def notificar(texto, nid):
    ctx = PythonService.mService
    nm = cast('android.app.NotificationManager',
              ctx.getSystemService(Context.NOTIFICATION_SERVICE))

    if SDK >= 26:
        Canal = autoclass('android.app.NotificationChannel')
        canal = Canal(CANAL, 'Lembretes', 3)   # 3 = padrão, mas sem som
        canal.setSound(None, None)
        canal.enableVibration(False)
        nm.createNotificationChannel(canal)
        b = Builder(ctx, CANAL)
    else:
        b = Builder(ctx)

    # Ao tocar na notificação, abre o app
    intent = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName())
    intent.setFlags(268435456 | 536870912)  # NEW_TASK | SINGLE_TOP
    pi = PendingIntent.getActivity(ctx, nid, intent, 67108864 | 134217728)  # IMMUTABLE | UPDATE_CURRENT

    b.setContentTitle('Lembrete')
    b.setContentText(texto)
    b.setSmallIcon(ctx.getApplicationInfo().icon)
    b.setAutoCancel(True)
    b.setContentIntent(pi)
    nm.notify(nid, b.build())


def main():
    try:
        PythonService.mService.setAutoRestartService(True)
    except Exception as e:
        print('autorestart:', e)

    while True:
        agora = time.time()
        rems = carregar(RFILE, [])
        feitos = set(carregar(FFILE, []))
        mudou = False
        for r in rems:
            if r['id'] in feitos or r['quando'] > agora:
                continue
            # se o celular ficou desligado por mais de 12h, não avisa mais
            if agora - r['quando'] < 12 * 3600:
                try:
                    notificar(r['texto'], int(r['id'][:7], 16))
                except Exception as e:
                    print('notificar:', e)
            feitos.add(r['id'])
            mudou = True
        ids = set(r['id'] for r in rems)
        limpos = [i for i in feitos if i in ids]
        if mudou or len(limpos) != len(feitos):
            salvar(FFILE, limpos)
        time.sleep(10)


main()
