import os
import re
import json
import time
import uuid
import random
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
CONFIG = os.path.join(BASE, 'config.json')     # nomes (a IA e você), vale p/ todas as conversas
COD_VOZ = 4321


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


def escolha(*opcoes):
    return random.choice(opcoes)


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


def _bordas(t):
    # tira palavrinhas soltas (de, para, às...) das pontas do texto
    for _ in range(3):
        t = re.sub(r'^(?:de|do|da|para|pra|que|a|as|às|em|no|na|e)\s+', '', t, flags=re.I)
        t = re.sub(r'\s+(?:de|do|da|para|pra|que|a|as|às|em|no|na|e)$', '', t, flags=re.I)
        t = t.strip(' ,.;:-')
    return t


def limpar(texto, cortes):
    t = texto
    for a, b in sorted(cortes, reverse=True):
        t = t[:a] + t[b:]
    t = re.sub(r'\s+', ' ', t).strip(' ,.;:-')
    t = _bordas(t)
    t = re.sub(
        r'^(?:por favor\W*)?(?:(?:eu\s+)?quero\s+(?:um\s+)?)?'
        r'(?:(?:marc|cri|agend|coloc)\w*\s+(?:um\s+)?)?(?:me\s+)?'
        r'(?:lembr|avis|notific)\w*(?:\s+(?:de|do|da|para|pra|que|sobre|a))?\s*',
        '', t, flags=re.I)
    t = _bordas(t)
    if not t:
        return 'Lembrete'
    return t[:1].upper() + t[1:]


HW = r'\d{1,2}|uma|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze'
HORAS_PAL = {'uma': 1, 'duas': 2, 'tres': 3, 'quatro': 4, 'cinco': 5, 'seis': 6,
             'sete': 7, 'oito': 8, 'nove': 9, 'dez': 10, 'onze': 11, 'doze': 12}
MINALT = r'meia|quarenta e cinco|vinte e cinco|quinze|vinte|trinta|dez|cinco|\d{1,2}'
MIN_PAL = {'meia': 30, 'quarenta e cinco': 45, 'vinte e cinco': 25, 'quinze': 15,
           'vinte': 20, 'trinta': 30, 'dez': 10, 'cinco': 5}


def _h(tok):
    return int(tok) if tok.isdigit() else HORAS_PAL[tok]


def _m(tok):
    return int(tok) if tok.isdigit() else MIN_PAL[tok]


# Formas de dizer o horário: 14:10, 14h10, 14h10min, às 14 e 10, 2 e meia, meio-dia e quinze...
TEMPOS = [
    (r'\b(?:(?:as|a)\s+)?(\d{1,2}):(\d{2})\b',
     lambda m: (int(m.group(1)), int(m.group(2)))),
    (r'\bmeio[- ]dia\s+e\s+(' + MINALT + r')(?:\s*min\w*)?\b',
     lambda m: (12, _m(m.group(1)))),
    (r'\b(?:as\s+(' + HW + r')|(\d{1,2})\s*(?:h|horas?))\s+e\s+(' + MINALT + r')(?:\s*min\w*)?\b',
     lambda m: (_h(m.group(1) or m.group(2)), _m(m.group(3)))),
    (r'\bas\s+(\d{1,2})\.(\d{2})\b',
     lambda m: (int(m.group(1)), int(m.group(2)))),
    (r'\b(?:(?:as|a)\s+)?(\d{1,2})\s*h(?:oras?)?(?:\s*(\d{2})(?:\s*min\w*)?)?(?![a-z0-9])',
     lambda m: (int(m.group(1)), int(m.group(2) or 0))),
    (r'\bas\s+(' + HW + r')(?:\s+horas?)?\b',
     lambda m: (_h(m.group(1)), 0)),
    (r'\bmeio[- ]dia\b', lambda m: (12, 0)),
    (r'\bmeia[- ]noite\b', lambda m: (0, 0)),
]


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
            extra = 0
            m2 = re.match(r'\s+e\s+(meia|(\d{1,2})\s*min\w*)', p[m.end():])
            if m2:
                extra = 30 if m2.group(1) == 'meia' else int(m2.group(2))
                cortes.append((m.end(), m.end() + m2.end()))
            return agora + timedelta(hours=n, minutes=extra), limpar(texto, cortes)
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
    for rx, f in TEMPOS:
        m = achar(rx)
        if m:
            hh, mm = f(m)
            break

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
# Lembretes fixos (repetem toda semana)
# ---------------------------------------------------------------
DIA_RX = r'(segunda|terca|quarta|quinta|sexta|sabado|domingo)s?(?:[- ]feiras?)?'
NOMES_DIAS = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']


def parse_fixo(texto):
    # Devolve (dias, hora, minuto, tarefa) se for um lembrete que se repete; senão None.
    p = plain(texto)
    cortes = []
    dias = None

    m = re.search(r'\b(?:de\s+)?' + DIA_RX + r'\s+(?:a|ate)\s+' + DIA_RX + r'\b', p)
    if m:
        a, b = DIAS[m.group(1)], DIAS[m.group(2)]
        dias = [(a + i) % 7 for i in range((b - a) % 7 + 1)]
        cortes.append(m.span())
    if dias is None:
        m = re.search(r'\b(?:todos\s+os\s+dias|todo\s+(?:santo\s+)?dia|diariamente|cada\s+dia)\b', p)
        if m:
            dias = list(range(7))
            cortes.append(m.span())
    if dias is None:
        m = re.search(r'\b(?:dias\s+uteis|durante\s+a\s+semana)\b', p)
        if m:
            dias = [0, 1, 2, 3, 4]
            cortes.append(m.span())
    if dias is None:
        m = re.search(r'\b(?:(?:aos|nos|no|em)\s+)?(?:fins?|finais?)\s+de\s+semana\b', p)
        if m:
            dias = [5, 6]
            cortes.append(m.span())
    if dias is None:
        m = (re.search(r'\btod[oa]s?(?:\s+(?:as|os))?\s+' + DIA_RX, p) or
             re.search(r'\b(?:as|aos|nas|nos)\s+(?:segunda|terca|quarta|quinta|sexta|sabado|domingo)s\b', p))
        if m:
            achados = set()
            for mm in re.finditer(DIA_RX, p):
                achados.add(DIAS[mm.group(1)])
                cortes.append(mm.span())
            if m.re.pattern.startswith(r'\btod'):
                cortes.append((m.start(), m.start(1)))
            else:
                cortes.append((m.start(), m.start() + 2))
            dias = sorted(achados)
    if not dias:
        return None

    sem = texto
    for a, b in sorted(cortes, reverse=True):
        sem = sem[:a] + ' ' + sem[b:]
    quando, tarefa = parse(sem, datetime.now())
    if quando is None:
        return sorted(set(dias)), None, None, limpar(sem, [])
    return sorted(set(dias)), quando.hour, quando.minute, tarefa


def desc_dias(dias):
    d = sorted(set(dias))
    if d == list(range(7)):
        return 'todos os dias'
    if d == [0, 1, 2, 3, 4]:
        return 'de segunda a sexta'
    if d == [5, 6]:
        return 'aos fins de semana'
    if len(d) == 1:
        return ('todo ' if d[0] >= 5 else 'toda ') + NOMES_DIAS[d[0]]
    nomes = [NOMES_DIAS[i] for i in d]
    return 'em ' + ', '.join(nomes[:-1]) + ' e ' + nomes[-1]


def ultima_ocorrencia(r, agora):
    # Último horário (já passado) em que este lembrete fixo deveria ter avisado.
    d = datetime.fromtimestamp(agora)
    for k in range(8):
        dia = (d - timedelta(days=k)).date()
        if dia.weekday() in r['dias']:
            occ = datetime(dia.year, dia.month, dia.day, r['h'], r['m'])
            if occ <= d:
                return occ.timestamp()
    return None


# ---------------------------------------------------------------
# Nomes: o da IA (começa como Jane) e o seu (começa como Angela)
# ---------------------------------------------------------------
N = r'([a-z]{2,20})'
IA_PAD = [
    r'\b(?:vou|quero)\s+(?:te|lhe)\s+chamar\s+de\s+' + N,
    r'\b(?:vou|quero)\s+chamar\s+voce\s+de\s+' + N,
    r'\bte\s+chamo\s+de\s+' + N,
    r'\b(?:muda|mude|mudar|troca|troque|trocar)\s+(?:o\s+)?seu\s+nome\s+(?:pra|para|por|de)\s+' + N,
    r'\bseu\s+nome\s+(?:agora\s+)?(?:e|sera)\s+' + N,
    r'\bvoce\s+(?:agora\s+)?(?:se\s+chama|vai\s+se\s+chamar)\s+' + N,
]
EU_PAD = [
    r'\bmeu\s+nome\s+(?:agora\s+)?e\s+' + N,
    r'\b(?:me\s+chama|me\s+chame|pode\s+me\s+chamar|me\s+chamar)\s+de\s+' + N,
]


def achar_nome(p, t, padroes):
    for rx in padroes:
        m = re.search(rx, p)
        if m:
            return t[m.start(1):m.end(1)].capitalize()
    return None


# ---------------------------------------------------------------
# Interface (tema escuro)
# ---------------------------------------------------------------
FUNDO = (0.07, 0.08, 0.11, 1)


class Bolha(Label):
    bg = ListProperty([0.17, 0.18, 0.23, 1])


KV = '''
<Button>:
    background_normal: ''
    background_down: ''
    background_color: (0.32, 0.36, 0.54, 1) if self.state == 'down' else (0.20, 0.22, 0.31, 1)
    color: 0.93, 0.93, 0.97, 1

<TextInput>:
    background_normal: ''
    background_active: ''
    background_color: 0.15, 0.16, 0.22, 1
    foreground_color: 0.95, 0.95, 0.98, 1
    hint_text_color: 0.52, 0.55, 0.66, 1
    cursor_color: 0.70, 0.76, 1, 1
    padding: dp(12), dp(14), dp(12), dp(12)

<Popup>:
    background: ''
    background_color: 0.11, 0.12, 0.17, 1
    separator_color: 0.45, 0.50, 0.85, 1
    title_color: 0.93, 0.93, 0.97, 1

<Bolha>:
    size_hint_y: None
    text_size: self.width - dp(24), None
    height: self.texture_size[1] + dp(24)
    valign: 'middle'
    color: 0.93, 0.93, 0.97, 1
    canvas.before:
        Color:
            rgba: self.bg
        RoundedRectangle:
            pos: self.x + dp(4), self.y + dp(2)
            size: self.width - dp(8), self.height - dp(4)
            radius: [dp(14)]

BoxLayout:
    orientation: 'vertical'
    canvas.before:
        Color:
            rgba: 0.07, 0.08, 0.11, 1
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
            color: 0.93, 0.93, 0.97, 1
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
            text: 'Voz'
            size_hint_x: 0.2
            on_release: app.ouvir()
        Button:
            text: 'Enviar'
            size_hint_x: 0.24
            on_release: app.enviar()
'''


class LembretesApp(App):
    title = 'Lembretes'

    # ---------- ciclo de vida ----------
    def build(self):
        Window.clearcolor = FUNDO
        Window.softinput_mode = 'below_target'
        cfg = carregar(CONFIG, {})
        self.ia = cfg.get('ia') or 'Jane'
        self.eu = cfg.get('eu') or 'Angela'
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
                from android import activity
                activity.bind(on_activity_result=self.resultado_voz)
            except Exception as e:
                print('voz:', e)
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

    def salvar_config(self):
        salvar(CONFIG, {'ia': self.ia, 'eu': self.eu})

    # ---------- voz ----------
    def ouvir(self):
        c = self.conversa()
        if platform != 'android':
            self.add(c, 'ia', 'O microfone só funciona no celular.')
            return
        try:
            from android import mActivity
            from jnius import autoclass
            Intent = autoclass('android.content.Intent')
            RS = autoclass('android.speech.RecognizerIntent')
            i = Intent(RS.ACTION_RECOGNIZE_SPEECH)
            i.putExtra(RS.EXTRA_LANGUAGE_MODEL, RS.LANGUAGE_MODEL_FREE_FORM)
            i.putExtra(RS.EXTRA_LANGUAGE, 'pt-BR')
            i.putExtra(RS.EXTRA_PREFER_OFFLINE, True)
            i.putExtra(RS.EXTRA_PROMPT, 'Pode falar, {}...'.format(self.eu))
            mActivity.startActivityForResult(i, COD_VOZ)
        except Exception as e:
            print('ouvir:', e)
            self.add(c, 'ia', 'Não consegui abrir o microfone. Seu celular tem o reconhecimento de voz do Google instalado?')

    def resultado_voz(self, requisicao, resultado, dados):
        if requisicao != COD_VOZ or resultado != -1 or dados is None:
            return
        try:
            from jnius import autoclass
            RS = autoclass('android.speech.RecognizerIntent')
            lista = dados.getStringArrayListExtra(RS.EXTRA_RESULTS)
            if lista is not None and lista.size() > 0:
                texto = str(lista.get(0))
                Clock.schedule_once(lambda dt: self.voz_ok(texto), 0)
        except Exception as e:
            print('resultado_voz:', e)

    def voz_ok(self, texto):
        self.root.ids.entrada.text = texto
        self.enviar()

    # ---------- conversas ----------
    def boas_vindas(self):
        return ('Oi, {eu}! Eu sou a {ia}. Me conta o que você quer lembrar e quando, '
                'digitando ou falando no botão Voz. Por exemplo: me lembra de tomar água '
                'amanhã às 15h.\n'
                'Eu só mando uma notificação suave, sem alarme, tá bom?').format(
                    eu=self.eu, ia=self.ia)

    def conversa(self, cid=None):
        cid = cid or self.cur
        for c in self.chats:
            if c['id'] == cid:
                return c
        return self.chats[0]

    def nova_conversa(self, render=True):
        c = {'id': uuid.uuid4().hex[:8], 'nome': 'Nova conversa',
             'msgs': [{'q': 'ia', 't': self.boas_vindas()}], 'pendente': ''}
        self.chats.insert(0, c)
        salvar(CFILE, self.chats)
        if render:
            self.cur = c['id']
            self.mostrar()
        return c

    def bolha(self, m):
        eu = m['q'] == 'eu'
        return Bolha(text=m['t'], halign='right' if eu else 'left',
                     bg=[0.22, 0.30, 0.48, 1] if eu else [0.17, 0.18, 0.23, 1])

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
        eu, ia = self.eu, self.ia

        # --- trocar nomes ---
        novo = achar_nome(p, t, IA_PAD)
        if novo:
            self.ia = novo
            self.salvar_config()
            return escolha(
                'Que nome lindo! A partir de agora eu sou a {}. Já guardei para todas as nossas conversas.',
                'Adorei! Pode me chamar de {} sempre que quiser. Salvei para todas as conversas.',
            ).format(novo)
        novo = achar_nome(p, t, EU_PAD)
        if novo:
            self.eu = novo
            self.salvar_config()
            return escolha(
                'Prazer, {}! Vou te chamar assim sempre, em todas as conversas.',
                'Combinado, {}! Guardei seu nome com carinho.',
            ).format(novo)

        # --- cancelar / listar ---
        if c.get('pendente') and re.search(r'\b(cancela\w*|esquece|deixa pra la)\b', p):
            c['pendente'] = ''
            return 'Tudo bem, {}, esqueci esse. Quando quiser, é só me dizer outro.'.format(eu)
        if re.search(r'\b(meus lembretes|lista|listar|o que tenho|proximos)\b', p):
            return self.resumo()

        # --- lembrete ---
        agora = datetime.now()
        texto = (c.get('pendente', '') + ' ' + t).strip()

        # --- lembrete fixo (repete toda semana) ---
        fx = parse_fixo(texto)
        if fx:
            dias, hh, mm, tarefa = fx
            if hh is None:
                c['pendente'] = texto
                return 'Que horas devo te avisar {}, {}?'.format(desc_dias(dias), eu)
            c['pendente'] = ''
            rems = carregar(RFILE, [])
            rems.append({'id': uuid.uuid4().hex, 'texto': tarefa, 'dias': dias,
                         'h': hh, 'm': mm, 'quando': 0, 'criado': time.time(),
                         'visto_ate': time.time(), 'chat': c['id']})
            salvar(RFILE, rems)
            if c['nome'] == 'Nova conversa':
                c['nome'] = tarefa[:28]
                self.root.ids.titulo.text = c['nome']
            return escolha(
                'Combinado, {eu}! "{t}", {d} às {h:02d}:{m:02d}. Esse lembrete fica ligado a esta conversa: se você apagar a conversa, ele para.',
                'Pronto, {eu}! Vou te lembrar de "{t}" {d} às {h:02d}:{m:02d}. Se apagar esta conversa, esse lembrete fixo some junto.',
            ).format(eu=eu, t=tarefa, d=desc_dias(dias), h=hh, m=mm)
        quando, tarefa = parse(texto, agora)
        if quando is None:
            if not c.get('pendente'):
                social = self.conversar(p)
                if social:
                    return social
            c['pendente'] = texto
            return escolha(
                'Entendi, {eu}: "{t}". Para quando você quer que eu te avise? Pode ser "amanhã às 15h" ou "daqui a 2 horas".',
                'Anotei "{t}", {eu}. Me diz quando devo te lembrar? Por exemplo: "hoje às 18h".',
            ).format(eu=eu, t=limpar(texto, []))
        c['pendente'] = ''
        if quando <= agora:
            return 'Esse horário já passou, {}. Pode escrever de novo com outro dia ou hora?'.format(eu)

        rems = carregar(RFILE, [])
        rems.append({'id': uuid.uuid4().hex, 'texto': tarefa,
                     'quando': quando.timestamp(), 'chat': c['id'], 'visto': False})
        salvar(RFILE, rems)
        if c['nome'] == 'Nova conversa':
            c['nome'] = tarefa[:28]
            self.root.ids.titulo.text = c['nome']
        return escolha(
            'Pronto, {eu}! Vou te avisar: "{t}", {q}. Pode ficar tranquila, é só uma notificação suave.',
            'Anotado com carinho! "{t}", {q}. Eu cuido disso por você, {eu}.',
            'Tá guardado, {eu}! "{t}", {q}. Sem alarme, só um aviso gentil.',
        ).format(eu=eu, t=tarefa, q=fmt(quando, agora))

    def conversar(self, p):
        """Respostas de conversa leve, sem precisar de internet."""
        eu, ia = self.eu, self.ia
        if re.search(r'\b(quem e voce|como voce se chama|qual (?:e )?(?:o )?seu nome)\b', p):
            return ('Eu sou a {ia}, sua ajudante de lembretes, {eu}. Se quiser me dar outro nome, '
                    'é só dizer "seu nome agora é..." e eu guardo.').format(ia=ia, eu=eu)
        if re.search(r'\b(ajuda|como funciona|o que voce faz)\b', p):
            return ('Eu guardo seus lembretes e te aviso com uma notificação suave, {eu}. '
                    'Diga, por exemplo: "me lembra de ligar para a mãe amanhã às 10h".\n'
                    'Também faço lembretes fixos: "de segunda a sexta às 8h me lembra de beber água" ou "toda quinta às 10h me lembra de ir ao mercado". Eles param se você apagar a conversa.\n'
                    'Comandos: "meus lembretes" mostra a lista; "me chama de ..." muda o seu nome; '
                    '"seu nome agora é ..." muda o meu.').format(eu=eu)
        if re.search(r'\b(cansad\w*|ansios\w*|estressad\w*|sobrecarregad\w*)\b', p):
            return ('Sinto muito que esteja assim, {eu}. Vamos com calma, um passo de cada vez. '
                    'Me conta o que você precisa lembrar e eu cuido dos horários por você.').format(eu=eu)
        if re.search(r'\b(obrigad\w*|brigad\w*|valeu)\b', p):
            return escolha('Imagina, {eu}! Estou aqui sempre que precisar.',
                           'Por nada, {eu}! Foi um prazer ajudar.').format(eu=eu)
        if re.search(r'^\W*(oi+|ola|opa|eae|e ai|hey|bom dia|boa tarde|boa noite)\b', p):
            return escolha('Oi, {eu}! Que bom te ver. O que você quer lembrar hoje?',
                           'Olá, {eu}! Aqui é a {ia}. Em que posso te ajudar?').format(eu=eu, ia=ia)
        return None

    def futuros(self):
        agora = time.time()
        fut = [r for r in carregar(RFILE, []) if r.get('dias') is None and r['quando'] > agora]
        return sorted(fut, key=lambda r: r['quando'])

    def fixos(self):
        return [r for r in carregar(RFILE, []) if r.get('dias') is not None]

    def resumo(self):
        fut, fix = self.futuros(), self.fixos()
        if not fut and not fix:
            return 'Você não tem lembretes pendentes, {}. Tudo em dia!'.format(self.eu)
        agora = datetime.now()
        linhas = ['- {} ({} às {:02d}:{:02d}, fixo)'.format(r['texto'], desc_dias(r['dias']), r['h'], r['m'])
                  for r in fix]
        linhas += ['- {} ({})'.format(r['texto'], fmt(datetime.fromtimestamp(r['quando']), agora))
                   for r in fut[:15]]
        return 'Seus lembretes, {}:\n'.format(self.eu) + '\n'.join(linhas)

    def tick(self, dt):
        # Quando um lembrete chega na hora, mostra a mensagem dentro do app.
        rems = carregar(RFILE, [])
        agora = time.time()
        mudou = False
        for r in rems:
            if r.get('dias') is not None:
                occ = ultima_ocorrencia(r, agora)
                if occ and occ > r.get('visto_ate', r.get('criado', 0)):
                    if agora - occ < 3 * 3600:
                        self.add(self.conversa(r['chat']), 'ia',
                                 'Ei, {}! Está na hora: {}'.format(self.eu, r['texto']))
                    r['visto_ate'] = occ
                    mudou = True
                continue
            if r['quando'] <= agora and not r.get('visto'):
                self.add(self.conversa(r['chat']), 'ia',
                         'Ei, {}! Está na hora: {}'.format(self.eu, r['texto']))
                r['visto'] = True
                mudou = True
        novos = [r for r in rems
                 if r.get('dias') is not None or not r.get('visto') or r['quando'] > agora - 7 * 86400]
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
        fix, fut = self.fixos(), self.futuros()
        if not fix and not fut:
            linhas.append(Label(text='Nenhum lembrete pendente.', size_hint_y=None, height=dp(48)))
        holder = {}
        itens = [(r, '{}\nFixo: {} às {:02d}:{:02d}'.format(r['texto'], desc_dias(r['dias']), r['h'], r['m']))
                 for r in fix]
        itens += [(r, '{}\n{}'.format(r['texto'], fmt(datetime.fromtimestamp(r['quando']), agora)))
                  for r in fut]
        for r, txt in itens:
            linha = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(6))
            lb = Label(text=txt, halign='left', valign='middle')
            lb.bind(size=lambda w, s: setattr(w, 'text_size', s))
            bt = Button(text='Apagar', size_hint_x=0.3)
            bt.bind(on_release=lambda x, i=r['id']: self.apagar(i, holder))
            linha.add_widget(lb)
            linha.add_widget(bt)
            linhas.append(linha)
        holder['pop'] = self.lista_popup('Meus lembretes', linhas)

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
        # lembretes fixos pertencem à conversa: sem a conversa, eles param
        salvar(RFILE, [r for r in carregar(RFILE, []) if not (r.get('dias') is not None and r.get('chat') == cid)])
        if self.cur == cid:
            self.cur = self.chats[0]['id']
            self.mostrar()
        holder['pop'].dismiss()
        self.abrir_conversas()


if __name__ == '__main__':
    LembretesApp().run()
