# Continuazione Mining a 49 regioni: tentativo CHR dopo COB e MCU

28 ottobre 2026. **Non è stato completato un terzo settore.** Il database accettato resta quello con COB e MCU, 49 regioni e 78 settori totali. CHR è l'estrazione di cromo. Entrambi i tentativi si sono fermati nel solver, prima della pulizia e della validazione dei risultati: nessuna soluzione `optimal` è stata scartata per residui monetari.

## Perimetro

Ripresa dal checkpoint già verificato COB → MCU, con il suo workbook dei 65 settori rimanenti. Il piano separa i 15 Mining ancora da completare in passi da un settore ciascuno e lascia gli altri 50 fuori dalla prova. Non sono stati modificati MARIO, CVXLab, funzione obiettivo, vincoli, pesi, scala, baseline, prior, output o target di trade. Nessuna nuova riconciliazione dei dati e nessun fallback ad altri modelli o solver.

Il primo avvio tecnico, prima dei solver, aveva usato il workbook completo originale. Il controllo dei fingerprint di MCU lo ha fermato, perché il checkpoint aveva registrato il workbook della fase intermedia. Si è quindi utilizzato il file `remaining_add_sectors.xlsx` salvato dal checkpoint, come previsto dalla ripresa normale. Non è stato disattivato alcun controllo d'integrità. Sul file rimanente cambia esclusivamente il foglio `Intermediate steps`; il ledger completo dei target è conservato separatamente per gli audit. Questo primo avvio non ha eseguito ottimizzazioni.

## Due tentativi numerici, una sola variante mirata

| Tentativo CHR | Esito nativo Gurobi | Stato riportato da CVXPY | Solver nativo | Intera esecuzione | Picco fisico |
|---|---|---|---:|---:|---:|
| Metodo automatico, barrier | Sub-optimal termination | user_limit | 13,39 s | 242,74 s | 6,32 GiB |
| `Method=1`, simplex | Infeasible or unbounded | infeasible_or_unbounded | 111,27 s | 272,13 s | 6,28 GiB |

Il primo stato `user_limit` non corrisponde al raggiungimento dei 600 secondi configurati: l'adattatore CVXPY mappa anche lo stato nativo Gurobi `SUBOPTIMAL` su quella stessa etichetta. Non sono stati raggiunti neppure i limiti esterni di 10 GiB o 1.800 secondi.

La singola alternativa simplex è stata scelta perché la [documentazione Gurobi sui problemi numerici](https://docs.gurobi.com/projects/optimizer/en/current/concepts/numericguide/numeric_parameters.html) indica il simplex come possibile alternativa al barrier; il [parametro Method](https://docs.gurobi.com/projects/optimizer/en/current/reference/parameters.html#parameter:Method) lo supporta per i QP continui. L'unica opzione cambiata è `Method=1`. Le tolleranze restano `FeasibilityTol=1e-9`, `OptimalityTol=1e-9` e `BarConvTol=1e-10`. I **24 CSV numerici sono identici byte per byte**, e l'impronta del modello Gurobi è la stessa: `0xd831e214`. Non sono state avviate altre varianti o prove su settori successivi.

## Che cosa sappiamo e che cosa resta da capire

I controlli di output e trade del solo CHR passano in tutte le 49 regioni, comprese le 2.352 rotte estere esplicite. Anche il controllo LP preliminare riporta `optimal` in entrambi i tentativi. Tuttavia quel controllo applica una banda numerica alle righe affini: non certifica la fattibilità esatta del QP successivo. Con le unità della prova, la banda è di 1 USD per riga canonica, oltre alla tolleranza nativa del solver; il residuo massimo misurato in quella fase è 2 USD. Questi dati rimangono diagnostici, senza un nuovo tetto economico di accettazione.

La diversa gestione della precisione fra preflight e problema finale può contribuire alla discordanza, ma **non abbiamo isolato la causa**. Lo stato ambiguo del simplex non viene presentato come una prova che gli inventari siano economicamente impossibili. Neppure il log del barrier, da solo, consente di certificare una soluzione finale.

Un ulteriore controllo senza solver, sui file già disponibili, non trova:

- aggregati Z/Y/V non nulli che il nuovo passo costringa interamente a zero;
- aggregati Z negativi;
- aggregati negativi di Capital/Labor o altri fattori con dominio non negativo;
- conflitti diretti fra il segno dell'aggregato Y e i domini dei suoi figli.

Sono stati controllati 118.314 aggregati Z e 3.728 aggregati Y forzati a zero, senza conflitti. È un controllo locale dei vincoli più immediati, non una prova di fattibilità dell'intero sistema. La diagnostica successiva dovrà isolare la discordanza fra vincoli ereditati, precisione del preflight e ottimizzazione, prima di modificare il modello o i dati. Non è stato fatto alcun aggiustamento per far passare questa prova.

## File e ripartenza

Gli input e i log sono archiviati su WSP, sotto `Inventories/D2.8 inventories`, nelle cartelle:

- `20261028 1356 - 49 regions and 3 sectors` — tentativo barrier;
- `20261028 1402 - 49 regions and 3 sectors` — tentativo simplex.

Sono entrambe marcate `failed`, con **nessun nuovo database** associato. Il numero tre indica la taglia tentata, non tre nuovi settori completati. L'ultimo risultato accettato rimane `Database/D2.8/20261028 1230 - 49 regions and 2 sectors`, con E da ricalcolare.

I workspace locali sono `build/model_trials/20261028_qp49_mining_continuation_02` e `build/model_trials/20261028_qp49_mining_continuation_03_simplex`. I pacchetti conservano input esatti in ZIP verificati, log dei solver, profili di risorse, audit e riferimenti alla riconciliazione iniziale. I manifest confermano che checkpoint sorgente e workbook non sono cambiati. Non ci sono commit o push in questa attività.
