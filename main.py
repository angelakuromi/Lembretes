import os
import re
import json
import time
import uuid
import unicodedata
from datetime import datetime, date, timedelta

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.utils import platform

# Garante o fuso horário correto do celular
if platform == 'android':
    try:
        from jnius import autoclass
        os.environ['TZ'] = autoclass('java.util.TimeZone').getDefault().getID()
        time.tzset()
    except Exception as e:
        print('fuso:', e)

BASE = os.environ.get('ANDROID_PRIVATE') or os.path.dirname(os.path.abspath(__file__))
RFILE = os.path.join(BASE, 'lembretes.json')   # escrito só pelo app
CFILE = os.path.join(BASE, 'conversas.json')   # escrito só pelo app

BOAS_VINDAS = ('Oi! Me diga o que você quer lembrar e quando. '
               'Exemplo: me lembra de tomar água amanhã às 15h.\n'
               'Eu só mando uma notificação silenciosa, sem alarme.')


def carregar(caminho, padrao):
    try:
        with open(caminho, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return padrao


def salvar(caminho, dados):
    tmp = caminho + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False)
    os.replace(tmp, caminho)


# ---------------------------------------------------------------
# IA leve (offline): entende datas e horas em português
# ---------------------------------------------------------------
DIAS = {'segunda': 0, 'terca': 1, 'quarta': 2, 'quinta': 3,
        'sexta': 4, 'sabado': 5, 'domingo': 6}
NUMS = {'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3, 'quatro': 4,
        'cinco': 5, 'seis': 6, 'sete': 7, 'oito': 8, 'nove': 9, 'dez': 10,
        'quinze': 15, 'vinte': 20, 'trinta': 30, 'meia': 0.5}
NOMES = '|'.join(sorted(NUMS, key=len, reverse=True))


def plain(s):
    """minúsculas e sem acento, mantendo o mesmo tamanho do texto"""
    return ''.join(unicodedata.normalize('NFD', c)[0] for c in s).lower()


def limpar(texto, cortes):
    t = texto
    for a, b in sorted(cortes, reverse=True):
        t = t[:a] + t[b:]
    t = re.sub(r'\s+', ' ', t).strip(' ,.;:-')
    t = re.sub(
        r'^(?:por favor\W*)?(?:(?:eu\s+)?quero\s+(?:um\s+)?)?'
        r'(?:(?:marc|cri|agend|coloc)\w*\s+(?:um\s+)?)?(?:me\s+)?'
        r'(?:lembr|avis|notific)\w*(?:\s+(?:de|do|da|para|pra|que|sobre|a))?\s*',
        '', t, flags=re.I)
    for _ in range(3):
        t = re.sub(r'^(?:de|do|da|para|pra|que|a|as|às|em|no|na|e)\s+', '', t, flags=re.I)
        t = re.sub(r'\s+(?:de|do|da|para|pra|que|a|as|às|em|no|na|e)$', '', t, flags=re.I)
        t = t.strip(' ,.;:-')
    if not t:
        return 'Lembrete'
    return t[:1].upper() + t[1:]


def parse(texto, agora):
    """Devolve (datetime, tarefa) ou (None, texto) se não achou quando."""
    p = plain(texto)
    cortes = []

    def achar(rx):
        m = re.search(rx, p)
        if m:
            cortes.append(m.span())
        return m

    hoje = agora.date()
    dia = None

    # "daqui a 2 horas", "em 30 minutos", "em 3 dias"
    m = achar(r'\b(?:daqui a|daqui|em)\s+(\d+|' + NOMES +
              r')\s*(minutos?|min|horas?|hrs?|h|dias?|semanas?)\b')
    if m:
        g = m.group(1)
        n = int(g) if g.isdigit() else NUMS[g]
        u = m.group(2)
        if u.startswith('min'):
            return agora + timedelta(minutes=n), limpar(texto, cortes)
        if u.startswith('h'):
            return agora + timedelta(hours=n), limpar(texto, cortes)
        dias = n if u.startswith('d') else n * 7
        dia = hoje + timedelta(days=int(dias))

    if dia is None:
        if achar(r'\bdepois de amanha\b'):
            dia = hoje + timedelta(days=2)
        elif achar(r'\bamanha\b'):
            dia = hoje + timedelta(days=1)
        elif achar(r'\bhoje\b'):
            dia = hoje
        else:
            m = achar(r'\b(?:(?:na|no|nesta|neste|proxima|proximo)\s+)?'
                      r'(segunda|terca|quarta|quinta|sexta|sabado|domingo)'
                      r'(?:[- ]feira)?\b')
            if m:
                delta = (DIAS[m.group(1)] - hoje.weekday()) % 7 or 7
                dia = hoje + timedelta(days=delta)
            else:
                m = achar(r'\bdia (\d{1,2})\b')
                if m:
                    n = int(m.group(1))
                    try:
                        dia = hoje.replace(day=n)
                    except ValueError:
                        dia = None
                    if dia is not None and dia < hoje:
                        ano = hoje.year + (1 if hoje.month == 12 else 0)
                        mes = hoje.month % 12 + 1
                        try:
                            dia = date(ano, mes, n)
                        except ValueError:
                            dia = None

    hh = mm = None
    m = achar(r'\b(\d{1,2}):(\d{2})\b')
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
    else:
        m = achar(r'\b(\d{1,2})\s*h(?:oras?)?(?:\s*(\d{2}))?\b')
        if m:
            hh, mm = int(m.group(1)), int(m.group(2) or 0)
        else:
            m = achar(r'\bas (\d{1,2})\b')
            if m:
                hh, mm = int(m.group(1)), 0
            elif achar(r'\bmeio[- ]dia\b'):
                hh, mm = 12, 0
            elif achar(r'\bmeia[- ]noite\b'):
                hh, mm = 0, 0

    m = achar(r'\b(?:da|de|a|na|pela|pra)\s+(manha|tarde|noite|madrugada)\b')
    per = m.group(1) if m else None
    if hh is not None and per in ('tarde', 'noite') and hh < 12:
        hh += 12
    if hh is None and per:
        hh, mm = {'manha': (9, 0), 'tarde': (15, 0),
                  'noite': (20, 0), 'madrugada': (3, 0)}[per]

    if hh is None and dia is None:
        return None, texto
    if hh is not None and (hh > 23 or mm > 59):
        return None, texto

    inferido = dia is None
    if inferido:
        dia = hoje
    if hh is None:
        hh, mm = 9, 0
    quando = datetime(dia.year, dia.month, dia.day, hh, mm)
    if inferido and quando <= agora:
        quando += timedelta(days=1)
    return quando, limpar(texto, cortes)


def fmt(dt, agora):
    d = (dt.date() - agora.date()).days
    nome = 'hoje' if d == 0 else 'amanhã' if d == 1 else dt.strftime('%d/%m')
    return '{} às {:%H:%M}'.format(nome, dt)


# ---------------------------------------------------------------
# Interface
# ---------------------------------------------------------------
class Bolha(Label):
    bg = ListProperty([1, 1, 1, 1])


KV = '''
<Bolha>:
    size_hint_y: None
    text_size: self.width - dp(24), None
    height: self.texture_size[1] + dp(24)
    valign: 'middle'
    color: 0.1, 0.1, 0.1, 1
    canvas.before:
        Color:
            rgba: self.bg
        RoundedRectangle:
            pos: self.x + dp(4), self.y + dp(2)
            size: self.width - dp(8), self.height - dp(4)
            radius: [dp(12)]

BoxLayout:
    orientation: 'vertical'
    canvas.before:
        Color:
            rgba: 0.95, 0.95, 0.92, 1
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        size_hint_y: None
        height: dp(52)
        padding: dp(6)
        spacing: dp(6)
        Button:
            text: 'Conversas'
            size_hint_x: 0.32
            on_release: app.abrir_conversas()
        Label:
            id: titulo
            color: 0.1, 0.1, 0.1, 1
            bold: True
            shorten: True
            text_size: self.size
            halign: 'center'
            valign: 'middle'
        Button:
            text: 'Lembretes'
            size_hint_x: 0.32
            on_release: app.abrir_lembretes()
    ScrollView:
        id: scroll
        BoxLayout:
            id: msgs
            orientation: 'vertical'
            size_hint_y: None
            height: self.minimum_height
            spacing: dp(4)
            padding: dp(6)
    BoxLayout:
        size_hint_y: None
        height: dp(56)
        padding: dp(6)
        spacing: dp(6)
        TextInput:
            id: entrada
            hint_text: 'Escreva seu lembrete...'
            multiline: False
            write_tab: False
            on_text_validate: app.enviar()
        Button:
            text: 'Enviar'
            size_hint_x: 0.25
            on_release: app.enviar()
'''


class LembretesApp(App):
    title = 'Lembretes'

    # ---------- ciclo de vida ----------
    def build(self):
        Window.softinput_mode = 'below_target'
        self.chats = carregar(CFILE, [])
        if not self.chats:
            self.nova_conversa(render=False)
        self.cur = self.chats[0]['id']
        return Builder.load_string(KV)

    def on_start(self):
        self.mostrar()
        self.tick(0)
        Clock.schedule_interval(self.tick, 5)
        if platform == 'android':
            try:
                from android.permissions import request_permissions
                request_permissions(['android.permission.POST_NOTIFICATIONS'])
            except Exception as e:
                print('permissao:', e)
            Clock.schedule_once(self.iniciar_servico, 4)

    def on_pause(self):
        return True

    def on_resume(self):
        self.tick(0)

    def iniciar_servico(self, *a):
        try:
            from android import mActivity
            from jnius import autoclass
            nome = mActivity.getPackageName() + '.ServiceReminders'
            autoclass(nome).start(mActivity, '')
        except Exception as e:
            print('servico:', e)

    # ---------- conversas ----------
    def conversa(self, cid=None):
        cid = cid or self.cur
        for c in self.chats:
            if c['id'] == cid:
                return c
        return self.chats[0]

    def nova_conversa(self, render=True):
        c = {'id': uuid.uuid4().hex[:8], 'nome': 'Nova conversa',
             'msgs': [{'q': 'ia', 't': BOAS_VINDAS}], 'pendente': ''}
        self.chats.insert(0, c)
        salvar(CFILE, self.chats)
        if render:
            self.cur = c['id']
            self.mostrar()
        return c

    def bolha(self, m):
        eu = m['q'] == 'eu'
        return Bolha(text=m['t'], halign='right' if eu else 'left',
                     bg=[0.78, 0.9, 0.84, 1] if eu else [1, 1, 1, 1])

    def mostrar(self):
        ids = self.root.ids
        c = self.conversa()
        ids.titulo.text = c['nome']
        ids.msgs.clear_widgets()
        for m in c['msgs']:
            ids.msgs.add_widget(self.bolha(m))
        Clock.schedule_once(self.descer, 0.1)

    def descer(self, *a):
        self.root.ids.scroll.scroll_y = 0

    def add(self, c, quem, texto):
        m = {'q': quem, 't': texto}
        c['msgs'].append(m)
        salvar(CFILE, self.chats)
        if c['id'] == self.cur:
            self.root.ids.msgs.add_widget(self.bolha(m))
            Clock.schedule_once(self.descer, 0.1)

    # ---------- chat ----------
    def enviar(self):
        campo = self.root.ids.entrada
        t = campo.text.strip()
        if not t:
            return
        campo.text = ''
        c = self.conversa()
        self.add(c, 'eu', t)
        self.add(c, 'ia', self.responder(c, t))
        Clock.schedule_once(lambda dt: setattr(campo, 'focus', True), 0.1)

    def responder(self, c, t):
        p = plain(t)
        if c.get('pendente') and re.search(r'\b(cancela\w*|esquece|deixa pra la)\b', p):
            c['pendente'] = ''
            return 'Tudo bem, esqueci esse.'
        if re.search(r'\b(meus lembretes|lista|listar|o que tenho|proximos)\b', p):
            return self.resumo()

        agora = datetime.now()
        texto = (c.get('pendente', '') + ' ' + t).strip()
        quando, tarefa = parse(texto, agora)
        if quando is None:
            c['pendente'] = texto
            return ('Entendi: "{}". Para quando? Por exemplo: amanhã às 15h, '
                    'ou daqui a 2 horas.').format(limpar(texto, []))
        c['pendente'] = ''
        if quando <= agora:
            return 'Esse horário já passou. Escreva de novo com outro dia ou hora.'

        rems = carregar(RFILE, [])
        rems.append({'id': uuid.uuid4().hex, 'texto': tarefa,
                     'quando': quando.timestamp(), 'chat': c['id'], 'visto': False})
        salvar(RFILE, rems)
        if c['nome'] == 'Nova conversa':
            c['nome'] = tarefa[:28]
            self.root.ids.titulo.text = c['nome']
        return 'Pronto! Vou te avisar: "{}", {}. Só uma notificação, sem alarme.'.format(
            tarefa, fmt(quando, agora))

    def futuros(self):
        agora = time.time()
        fut = [r for r in carregar(RFILE, []) if r['quando'] > agora]
        return sorted(fut, key=lambda r: r['quando'])

    def resumo(self):
        fut = self.futuros()
        if not fut:
            return 'Você não tem lembretes pendentes.'
        agora = datetime.now()
        linhas = ['- {} ({})'.format(r['texto'], fmt(datetime.fromtimestamp(r['quando']), agora))
                  for r in fut[:15]]
        return 'Seus próximos lembretes:\n' + '\n'.join(linhas)

    def tick(self, dt):
        """Quando um lembrete chega na hora, mostra a mensagem dentro do app."""
        rems = carregar(RFILE, [])
        agora = time.time()
        mudou = False
        for r in rems:
            if r['quando'] <= agora and not r.get('visto'):
                self.add(self.conversa(r['chat']), 'ia', 'Lembrete: ' + r['texto'])
                r['visto'] = True
                mudou = True
        novos = [r for r in rems if not r.get('visto') or r['quando'] > agora - 7 * 86400]
        if mudou or len(novos) != len(rems):
            salvar(RFILE, novos)

    # ---------- janelas ----------
    def lista_popup(self, titulo, linhas, extra=None):
        caixa = BoxLayout(orientation='vertical', spacing=dp(6))
        if extra is not None:
            caixa.add_widget(extra)
        rolagem = ScrollView()
        grade = GridLayout(cols=1, size_hint_y=None, spacing=dp(6))
        grade.bind(minimum_height=grade.setter('height'))
        for w in linhas:
            grade.add_widget(w)
        rolagem.add_widget(grade)
        caixa.add_widget(rolagem)
        pop = Popup(title=titulo, content=caixa, size_hint=(0.94, 0.8))
        fechar = Button(text='Fechar', size_hint_y=None, height=dp(48))
        fechar.bind(on_release=pop.dismiss)
        caixa.add_widget(fechar)
        pop.open()
        return pop

    def abrir_lembretes(self):
        agora = datetime.now()
        linhas = []
        fut = self.futuros()
        if not fut:
            lb = Label(text='Nenhum lembrete pendente.', size_hint_y=None, height=dp(48))
            linhas.append(lb)
        holder = {}
        for r in fut:
            linha = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(6))
            lb = Label(text='{}\n{}'.format(r['texto'], fmt(datetime.fromtimestamp(r['quando']), agora)),
                       halign='left', valign='middle')
            lb.bind(size=lambda w, s: setattr(w, 'text_size', s))
            bt = Button(text='Apagar', size_hint_x=0.3)
            bt.bind(on_release=lambda x, i=r['id']: self.apagar(i, holder))
            linha.add_widget(lb)
            linha.add_widget(bt)
            linhas.append(linha)
        holder['pop'] = self.lista_popup('Próximos lembretes', linhas)

    def apagar(self, rid, holder):
        rems = [r for r in carregar(RFILE, []) if r['id'] != rid]
        salvar(RFILE, rems)
        holder['pop'].dismiss()
        self.abrir_lembretes()

    def abrir_conversas(self):
        holder = {}
        novo = Button(text='+ Nova conversa', size_hint_y=None, height=dp(52))

        def criar(*a):
            holder['pop'].dismiss()
            self.nova_conversa()
        novo.bind(on_release=criar)

        linhas = []
        for c in self.chats:
            linha = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
            b = Button(text=c['nome'], shorten=True, halign='left')
            b.bind(size=lambda w, s: setattr(w, 'text_size', (s[0] - dp(16), s[1])))
            b.bind(on_release=lambda x, i=c['id']: self.escolher(i, holder))
            linha.add_widget(b)
            if len(self.chats) > 1:
                x = Button(text='X', size_hint_x=0.2)
                x.bind(on_release=lambda w, i=c['id']: self.excluir(i, holder))
                linha.add_widget(x)
            linhas.append(linha)
        holder['pop'] = self.lista_popup('Conversas', linhas, extra=novo)

    def escolher(self, cid, holder):
        self.cur = cid
        holder['pop'].dismiss()
        self.mostrar()

    def excluir(self, cid, holder):
        self.chats = [c for c in self.chats if c['id'] != cid]
        salvar(CFILE, self.chats)
        if self.cur == cid:
            self.cur = self.chats[0]['id']
            self.mostrar()
        holder['pop'].dismiss()
        self.abrir_conversas()


if __name__ == '__main__':
    LembretesApp().run()
