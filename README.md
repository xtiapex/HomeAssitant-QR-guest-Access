# QR Guest Access (v1.0 · tappa 1)

Apri una porta con QR code temporanei, direttamente da Home Assistant.

- **Lettore**: l'integrazione `qrcode` di Home Assistant legge la telecamera (già provata e funzionante).
- **Questa integrazione**: crea i QR, decide se sono validi, apre la Shelly, tiene lo storico.
- **Pannello "Accessi ospiti"** nella barra laterale: crea QR (nome, inizio, fine, numero di accessi), scarica il PNG, revoca, prova scansioni senza telecamera, storico, anteprima camera.

Telegram arriverà nella tappa 3. Per ora tutto si gestisce dal pannello.

---

## 1. Prima di installare

Se avevi la **prima versione** del progetto:

1. *Impostazioni → Dispositivi e servizi → QR Guest Access → ⋮ → Elimina*.
2. Cancella la vecchia cartella `/config/custom_components/qr_guest_access`.
3. (Facoltativo) togli da `configuration.yaml` gli helper `input_text/input_select/input_number/input_datetime` e le automazioni `qr_guest_*` della vecchia versione, e cancella `/config/www/qr_guest_access`. Il vecchio bot Telegram va fermato.

I dati della vecchia versione (`.storage/qr_guest_access`) non vengono usati né toccati: la nuova versione usa un file suo.

## 2. Installazione

### Metodo consigliato: Marketplace di Home Assistant (2026.11 o successivo)

1. *Impostazioni → Marketplace*, accetta l'avviso sui rischi (solo la prima volta).
2. Cerca l'opzione **Add from link** (aggiungi da link) e incolla `https://github.com/xtiapex/HomeAssitant-QR-guest-Access`. Per i repository personalizzati il Marketplace chiede di collegarti a GitHub con l'accesso da dispositivo: approvi su GitHub, senza inserire password in HA.
3. Apri "QR Guest Access" e premi **Install**. Per una nuova integrazione non serve riavviare.
4. Passa direttamente alla configurazione (punto 3 qui sotto).

Gli aggiornamenti arrivano come aggiornamenti normali di Home Assistant, in base alle **release** pubblicate su GitHub (vedi la sezione "Aggiornare l'integrazione"). Senza release il Marketplace usa l'ultimo commit.

### Metodo manuale

1. Copia la cartella `custom_components/qr_guest_access` in `/config/custom_components/` (add-on *Samba share* o *File editor*).
2. **Riavvia Home Assistant.** Alla partenza installa da solo la libreria `segno` (serve a disegnare i QR): serve internet.
3. *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → "QR Guest Access"* e scegli:
   - **Lettore QR**: l'entità `image_processing.qr_...` che già funziona;
   - **Porta**: l'interruttore della Shelly 1;
   - **Telecamera** (facoltativa): solo per l'anteprima nel pannello;
   - **Secondi di apertura**: 3.
4. Nella barra laterale compare **Accessi ospiti** (solo per amministratori).

### Configurazione consigliata del lettore (`configuration.yaml`)

```yaml
camera:
  - platform: generic
    name: "Porta"
    still_image_url: "http://IP_CAMERA/ISAPI/Streaming/channels/101/picture"
    stream_source: "rtsp://admin:PASSWORD@IP_CAMERA:554/Streaming/Channels/101"
    username: admin
    password: PASSWORD
    authentication: digest
    verify_ssl: false

image_processing:
  - platform: qrcode
    scan_interval: 2
    source:
      - entity_id: camera.porta
        name: "QR Porta"
```

`scan_interval: 2` significa che la telecamera viene "guardata" ogni 2 secondi: tieni il QR fermo davanti alla camera per almeno 2-3 secondi.

### Rete di sicurezza sulla Shelly

Nelle impostazioni del relè della Shelly (web UI della Shelly, sezione *Timer* / *Auto-off*) imposta lo spegnimento automatico a **3 secondi**. L'integrazione spegne già il relè da sola, ma così la porta si richiude anche se Home Assistant si blocca mentre è aperta.

## 3. Primo test (a porta "chiusa")

All'installazione la **modalità test è attiva**: i QR validi vengono riconosciuti ma la porta non si apre e gli accessi non si scalano.

1. Apri **Accessi ospiti** e crea un QR (es. nome "Prova", scorciatoia *Monouso · 24 ore*, **Genera QR**).
2. **Scarica PNG** (o tieni premuto sull'immagine dal telefono) e mostralo alla telecamera, oppure aprilo sullo schermo del telefono.
3. Nello **Storico** compare la riga "Accesso consentito" con l'etichetta *test*.
4. Senza telecamera: *Prova una scansione → Simula scansione*.
5. Prova anche un QR qualsiasi (es. un link): deve comparire "QR sconosciuto".
6. Quando sei contento, disattiva **Modalità test** (in alto a destra, chiede conferma). Da lì un QR valido apre davvero la porta.

## 4. Regole di validità

| Stato | Significato |
|---|---|
| Attivo | dentro la finestra di validità e con accessi disponibili |
| In attesa | la data di inizio non è ancora arrivata |
| Scaduto | oltre la data di fine |
| Esaurito | accessi finiti |
| Revocato | revocato a mano |

- Monouso = 1 accesso; multiuso = N accessi; illimitato = nessun limite, **ma serve la data di fine**.
- L'accesso viene scalato **prima** di aprire la porta; se l'apertura fallisce, viene restituito.
- Lo stesso QR letto più volte in 10 secondi conta una volta sola.
- I QR contengono solo un codice casuale (`QG-` + 32 caratteri), mai nomi o dati.
- Un token non si modifica: se serve cambiare qualcosa, revoca e crea un nuovo QR.
- Gli orari nel pannello sono quelli del dispositivo che usi; nei servizi di HA, quelli del fuso orario di Home Assistant.

## 5. Per le automazioni

**Evento** `qr_guest_access_scan` (ad ogni scansione registrata): `name`, `result`, `door_opened`, `test`, `source`, `time`. Esiti: `granted`, `denied_unknown`, `denied_revoked`, `denied_expired`, `denied_not_started`, `denied_exhausted`, `error`.

```yaml
automation:
  - alias: "QR: avvisami quando qualcuno entra"
    triggers:
      - trigger: event
        event_type: qr_guest_access_scan
        event_data:
          result: granted
    conditions:
      - condition: template
        value_template: "{{ not trigger.event.data.test }}"
    actions:
      - action: notify.notify
        data:
          message: "{{ trigger.event.data.name }} ha aperto la porta"
```

**Sensori**: QR attivi, accessi consentiti, accessi negati, ultimo accesso.

**Azioni**: `qr_guest_access.create_qr` (nome, valido dal/fino al, numero di accessi, illimitati; restituisce i dati del token), `qr_guest_access.revoke_qr`, `qr_guest_access.simulate_scan`. Senza indicazioni `create_qr` crea un QR **monouso**.

## 6. Sicurezza: cosa sapere

- I token sono salvati **in chiaro** in `.storage` (così puoi riscaricare il QR quando vuoi). Chi ha accesso ai file o ai backup di Home Assistant può leggerli: proteggi i backup.
- Il pannello è riservato agli amministratori. Il file `panel.js` è raggiungibile senza login, ma contiene solo il codice dell'interfaccia, nessun dato.
- Le immagini dei QR non vengono salvate su disco: sono generate al momento.
- Chi fotografa un QR multiuso o illimitato può riusarlo finché è valido. Usa scadenze brevi e revoca quando serve.
- Tieni sempre una chiave o un'apertura manuale di riserva.

## 7. Se qualcosa non va

| Sintomo | Cosa controllare |
|---|---|
| "Configurazione di una versione precedente" | elimina l'integrazione vecchia e aggiungila di nuovo (punto 1) |
| Il pannello non compare | riavvia HA; controlla che l'utente sia amministratore; svuota la cache del browser |
| Nei log: errore su `segno` | HA non è riuscito a installarla (niente internet): i token si creano ma il QR non si disegna |
| Il QR non viene letto | controlla l'anteprima nel pannello: QR grande, a fuoco, senza riflessi; schermo del telefono alla massima luminosità |
| Lo stesso QR non riapre subito | è normale: cooldown di 10 secondi |
| La porta non si apre ma lo storico dice "consentito" | modalità test ancora attiva (banner giallo) |
| Storico con "Errore porta" | l'interruttore della Shelly non risponde: guarda i log di HA |

Log dettagliati: in `configuration.yaml`

```yaml
logger:
  logs:
    custom_components.qr_guest_access: debug
```

## 8. Sviluppo e test

```bash
python3 -m unittest discover -s tests -v
```

Contiene i test del motore di validazione e dei collegamenti con un Home Assistant finto. Non sostituiscono una prova su un HA vero (il pannello JavaScript e le API di HA vanno provati dal vivo).

Repository: https://github.com/xtiapex/HomeAssitant-QR-guest-Access

## 9. Aggiornare l'integrazione

A ogni modifica la versione va aumentata in **due** posti: `custom_components/qr_guest_access/manifest.json` (`version`) e `custom_components/qr_guest_access/const.py` (`VERSION`, serve a far ricaricare `panel.js` al browser). Poi su GitHub crea una **release** con lo stesso numero (es. `v1.0.1`): HACS segue le release.
