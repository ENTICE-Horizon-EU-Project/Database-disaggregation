# Continuazione Mining a 49 regioni — 23 ottobre 2026

**Esito: arresto nel controllo degli input, prima di qualsiasi nuova ottimizzazione.** Il checkpoint con CHR resta invariato; nessun nuovo settore o database è stato accettato. Non è un fallimento di KL o MOSEK e non è stato provato un altro solver o modello.

## Prova impostata

Ripartenza dal checkpoint `20261023 1404 - 49 regions and 1 sectors`, con CHR già inserito, 49 regioni e 77 settori totali. Ordine dei 16 passi previsti: MCU, COB, GRA, LIT, MAN, MAO, MGC, MIO, MUR, NIK, NIO, PGM, REE, SIL, TIT, ZIN. A completamento sarebbero 17 nuovi settori Mining e 93 settori totali. Gli altri 50 settori ENTICE restano fuori da questa prova.

Stesso modello `Split_sectors_MRIO_KL`, MOSEK con due thread e gli stessi parametri del checkpoint. Un processo separato per ogni settore; checkpoint dopo ogni successo. Nessun fallback alla quadratica. Nessuna modifica al codice di MARIO, CVXLab o al modello in questo tentativo; sono stati aggiunti solo gli script e gli artefatti di esecuzione nella cartella di lavoro.

## Preparazione effettuata su copie

È stata applicata la riconciliazione dei fattori già autorizzata: Capital/Labor non negativi; Tax/TTM possono essere negativi; somma netta di V conservata. Sono cambiati 37 profili settore–regione dei 16 Mining ancora da inserire; per ogni profilo la somma netta prima/dopo coincide. L'audit riporta tutte le celle e i valori originali e nuovi. È una trasformazione dei prior, non una nuova osservazione empirica.

Sono stati modificati soltanto i valori dei fattori interessati e il foglio `Intermediate steps` della copia. Tutti gli altri membri dell'archivio Excel, compresi output e trade, sono stati confrontati e sono identici. I file di partenza e tutti i file del checkpoint coperti dai checksum sono rimasti invariati.

## Perché il primo passo si ferma

Il preflight della pipeline controlla le disponibilità del settore padre prima di costruire il problema. Legge tutti i 66 settori ancora nel workbook e trova 128 rotte oltre il budget netto del padre: 103 riguardano i Mining e 25 altri settori. Sebbene il controllo includa quindi anche passi fuori dalla prova richiesta, il conflitto Mining è reale: MCU da solo eccede il budget su cinque rotte in cui il padre ha soltanto domanda finale non negativa.

| Rotta | Target MCU (milioni USD) | Trade rimasto in OXT (milioni USD) | Eccesso (milioni USD) |
|---|---:|---:|---:|
| BR → BG | 289.951618 | 289.627354 | 0.324264 |
| FI → IE | 0.113098 | 0.098194 | 0.014904 |
| TR → BG | 214.760874 | 211.098559 | 3.662316 |
| WE → AU | 15.245482 | 14.879701 | 0.365781 |
| WM → FI | 23.349441 | 23.314303 | 0.035138 |

Questi eccessi non possono essere risolti scegliendo una diversa funzione obiettivo: i target e le disponibilità sono incompatibili con i domini e i vincoli di aggregazione correnti. Non sono state allentate tolleranze o cancellati controlli per forzare la prosecuzione.

## L'esempio che chiarisce la causa

Sulla rotta Finlandia → Canada, prima di CHR il padre OXT forniva **156,594195 milioni USD**. Nel checkpoint questa quantità è ripartita fra **25,349001 milioni a CHR** e **131,245204 milioni rimasti in OXT**. I Mining ancora da inserire richiedono invece **156,594195 milioni** su quella rotta, quasi tutti per NIK.

Il workbook della prova CHR non contiene un'osservazione di trade CHR su questa rotta: il modello l'ha potuta allocare liberamente. Il singolo passo CHR può quindi essere accettato senza che sia rimasta capacità sufficiente per i target dei passi successivi. La variazione della somma OXT+CHR rispetto al padre iniziale è qui circa **10,13 USD**; la capacità assorbita da CHR è **25,35 milioni USD**. Il conflitto non è spiegato dalla pulizia dei piccoli negativi.

Sulle 103 rotte Mining segnalate, la somma degli eccessi dei target rispetto al budget netto residuo è **75,323077 milioni USD**; il massimo è **25,348991 milioni USD** su Finlandia → Canada. Sono eccessi di trade cumulativi, non errori contabili né una misura della distanza totale del database dalla baseline. Dove esiste domanda finale negativa il semplice budget netto richiede un controllo dei segni più accurato; le cinque violazioni individuali di MCU elencate sopra non hanno questa ambiguità.

## Le due strade possibili

1. **Mantenere questo checkpoint e riconciliare su una copia i target di trade dei 16 Mining con la capacità rimasta**, lasciando fissi output, baseline e CHR. È una nuova assunzione sui dati da approvare. Nel JSON diagnostico è riportata, solo per esame, la riduzione proporzionale minima per rientrare in ciascun budget netto: Finlandia → Canada richiederebbe circa −16,19% per i target Mining di quella rotta. Non è stata applicata e non certifica da sola la fattibilità del modello completo.
2. **Conservare i target dei Mining e rivedere il passo CHR**, prevedendo la capacità necessaria ai settori futuri. Richiede un nuovo checkpoint e una modifica esplicita alla gestione dei passi; non sarebbe una semplice continuazione di questo risultato.

Il preflight dovrà inoltre essere riferito ai passi effettivamente eseguiti dalla prova: i 50 settori fuori dalla prova non devono bloccare MCU. Correggere il perimetro del controllo, da solo, non elimina le incompatibilità Mining documentate.

## Artefatti

- `add_sectors.xlsx` nella cartella di questo tentativo: input completo con piano, riconciliazione dei fattori e target di output/trade originali.
- `diagnostics/plan.json`: ordine dei passi e hash degli input.
- `diagnostics/factor-reconciliation.json`: audit di ogni prior di V corretto.
- `diagnostics/parent_budgets.json`: controllo originale completo su 66 settori.
- `diagnostics/mining-trade-conflicts.json`: dettaglio delle 103 rotte Mining, confronto prima/dopo CHR e proposta diagnostica non applicata.
- `diagnostics/trial.log`, `resources.json`, `trial.json`: prova interrotta prima dei solver e risorse della sola preparazione/preflight; non sono un benchmark KL.

Non è stato prodotto un database con MCU. Il nome della cartella di input conta i due settori previsti per il tentativo (CHR e MCU), non due settori completati. E rimane da ricalcolare come nel checkpoint iniziale.

Verifica della pubblicazione: tutti i contenuti dei fogli Excel coincidono con la copia di lavoro. Nei due Excel pubblicati differisce `docProps/custom.xml` e sono presenti due voci aggiuntive sotto `[trash]/`; i file dei fogli sono identici. L'input esatto è conservato anche in `diagnostics/exact_trial_input.zip`, con hash verificato in `publication-integrity.json`; gli audit JSON pubblicati coincidono byte per byte.
