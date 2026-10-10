package org.meu.lembretes;

import android.app.Activity;
import android.app.NotificationManager;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.File;
import java.io.FileWriter;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

// Tela de lembrete: acende a tela em silencio (sem som e sem vibracao)
// e mostra um botao para confirmar, como um despertador sem alarme.
public class AlarmeActivity extends Activity {

    private String rid = "";
    private String occ = "0";
    private String arquivo = "";
    private int nid = 0;
    private final Handler handler = new Handler(Looper.getMainLooper());

    private String s(String v) {
        return v == null ? "" : v;
    }

    private TextView linha(String t, int sp, int cor, int estilo, int margemTopoDp) {
        TextView v = new TextView(this);
        v.setText(t);
        v.setTextSize(sp);
        v.setTextColor(cor);
        v.setTypeface(null, estilo);
        v.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = (int) (margemTopoDp * getResources().getDisplayMetrics().density);
        v.setLayoutParams(lp);
        return v;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        super.onCreate(savedInstanceState);

        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        }
        getWindow().addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                        | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                        | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        rid = s(getIntent().getStringExtra("rid"));
        occ = s(getIntent().getStringExtra("occ"));
        arquivo = s(getIntent().getStringExtra("afile"));
        String texto = s(getIntent().getStringExtra("texto"));
        String ia = s(getIntent().getStringExtra("ia"));
        String eu = s(getIntent().getStringExtra("eu"));
        try {
            nid = Integer.parseInt(s(getIntent().getStringExtra("nid")));
        } catch (Exception e) {
            nid = 0;
        }
        if (ia.length() == 0) {
            ia = "Jane";
        }

        float d = getResources().getDisplayMetrics().density;
        int violeta = Color.rgb(139, 92, 246);
        int claro = Color.rgb(237, 237, 247);
        int cinza = Color.rgb(160, 160, 176);

        LinearLayout raiz = new LinearLayout(this);
        raiz.setOrientation(LinearLayout.VERTICAL);
        raiz.setGravity(Gravity.CENTER);
        raiz.setBackgroundColor(Color.rgb(0, 0, 0));
        int p = (int) (28 * d);
        raiz.setPadding(p, p, p, p);

        raiz.addView(linha(ia, 16, violeta, Typeface.NORMAL, 0));

        String hora = new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date());
        TextView relogio = linha(hora, 72, claro, Typeface.NORMAL, 8);
        relogio.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        raiz.addView(relogio);

        String saudacao = eu.length() > 0 ? eu + ", \u00e9 hora de:" : "\u00c9 hora de:";
        raiz.addView(linha(saudacao, 18, cinza, Typeface.NORMAL, 36));
        raiz.addView(linha(texto, 30, claro, Typeface.BOLD, 10));

        Button ok = new Button(this);
        ok.setText("Entendi");
        ok.setAllCaps(false);
        ok.setTextSize(18);
        ok.setTextColor(Color.WHITE);
        GradientDrawable pilula = new GradientDrawable();
        pilula.setColor(violeta);
        pilula.setCornerRadius(40 * d);
        ok.setBackground(pilula);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                (int) (220 * d), (int) (56 * d));
        lp.topMargin = (int) (52 * d);
        ok.setLayoutParams(lp);
        ok.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                confirmar();
            }
        });
        raiz.addView(ok);

        setContentView(raiz);

        // se ninguem tocar em 3 minutos, a tela fecha sozinha (o aviso volta a tocar depois)
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                finishAndRemoveTask();
            }
        }, 180000);
    }

    private void confirmar() {
        try {
            File f = arquivo.length() > 0 ? new File(arquivo) : new File(getFilesDir(), "confirmados.txt");
            FileWriter w = new FileWriter(f, true);
            w.write(rid + "|" + occ + "\n");
            w.close();
        } catch (Exception e) {
            // sem problema
        }
        try {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            nm.cancel(nid);
        } catch (Exception e) {
            // sem problema
        }
        finishAndRemoveTask();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
