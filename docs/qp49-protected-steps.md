# Prova quadratica/Gurobi: 49 regioni, due inserimenti consecutivi

Aggiornamento: questo rapporto descrive l’ordine MCU → COB. Il successivo
esperimento COB → MCU ha completato entrambi i settori; vedi
[ordine e accettazione numerica](qp49-order-and-numerical-acceptance.md).

28 ottobre 2026. **Esito parziale: MCU completato, COB non completato.** Il risultato accettato contiene 49 regioni e 77 settori totali: i 76 iniziali più MCU. I due tentativi COB terminano per difficoltà numeriche di Gurobi; non esiste un database accettato con entrambi i nuovi settori.

## Impostazione

Si riparte dalla preparazione a 49 regioni **precedente a CHR**, evitando di ereditare il suo conflitto con i trade futuri. I passi richiesti sono `Mining MCU`, poi `Mining COB`, ciascuno in un processo separato. Il modello è quello esistente, `Split_sectors_MRIO_quadratic`, con Gurobi, due thread, accounting `inherit`, peso Y 0,1, peso supply 1, scala 1.000 e vincoli compatti. Capital/Labor restano non negativi; Tax/TTM possono avere entrambi i segni; Y conserva i domini di segno previsti. E rimane da ricalcolare.

Non sono stati modificati MARIO o CVXLab. L'unico cambiamento di codice per questa prova è nella pipeline: `reconcile_checkpoint_trade.py` può partire anche da una preparazione originale (`--prepared`), oltre che da un checkpoint. Script e audit dell'esecuzione restano nella cartella locale di lavoro. Non sono stati fatti commit o push.

## Come sono protetti i budget successivi

La riconciliazione viene eseguita **una sola volta prima di MCU**, congiuntamente per tutti i 17 Mining sulla baseline originale. Mantiene gli output, i prior tecnici e la baseline, e costruisce un piano completo di trade estero, compresi gli zeri dello scenario preparato. Gli altri 50 settori conservano i target precedenti. Gli zeri preparati non sono presentati come osservazioni empiriche certificate.

Il modello riceve quindi tutte le 2.352 rotte estere del settore attivo a ciascun passo: le rotte omesse non diventano nuove libertà che possano assorbire il trade dei settori futuri. La conservazione del totale del padre lascia nel padre residuo il budget non usato. Per controllare il risultato, dopo il passo si verificano i target di **tutti** i settori pendenti, anche quelli fuori dalla prova Mining.

Questo protegge i budget di output e trade entro le tolleranze numeriche. Non è una certificazione anticipata della fattibilità di tutti i futuri modelli MRIO, che possono avere ulteriori vincoli su celle, segni e contabilità.

La riconciliazione iniziale cambia 1,148 rotte di oltre 1 USD. La variazione assoluta sommata sulle rotte è **15.622984 miliardi USD**, circa **5.30%** del trade Mining iniziale. Il totale dei trade dei 17 Mining passa da **294.710291** a **305.558204 miliardi USD**. Sono variazioni sostanziali dei prior commerciali per compatibilità con i budget di riga, non semplici correzioni di arrotondamento. Sono tutte nell'audit; **nessun target è stato riconciliato o aggiornato fra MCU e COB**.

## Tempi e memoria misurati

| Passo/tentativo | Esito | NumericFocus | Ottimizzatore barrier | Intera prova locale | Picco footprint |
|---|---|---:|---:|---:|---:|
| MCU | accepted | 1 | 3.36 s | 214.79 s | 5.84 GiB |
| COB | failed | 1 | 12.23 s | 176.57 s | 6.31 GiB |
| COB | failed | 3 | 39.38 s | 204.00 s | 6.09 GiB |

Il tempo dell'intera prova include caricamento, preparazione MARIO/CVXLab, controllo preliminare di fattibilità, compilazione, soluzione e, per MCU, ricostruzione e salvataggio del checkpoint. Esclude la pubblicazione su WSP e gli audit successivi. Il costo del passo MCU è quindi in gran parte esterno all'ottimizzatore quadratico.

La memoria è il footprint fisico macOS del processo e dei suoi figli, campionato ogni 0,5 secondi; non è la RAM totale del Mac né soltanto RSS. Il monitor ha completato tutte le misure. Nessun tentativo è stato fermato per risorse: i limiti erano 10 GiB di footprint/RSS e 8 GiB di disco libero. La singola chiamata al solver aveva un limite di 600 secondi.

Questi dati dimostrano che il primo passo gira sul Mac da 18 GiB. I tentativi COB eseguiti rientrano anch'essi nel limite, ma il loro fallimento numerico impedisce di certificare una soluzione del secondo passo. Non sono una misura della RAM necessaria per tutti i 67 nuovi settori o per 163 regioni. Non è un confronto controllato con KL: settori, dati commerciali e condizioni iniziali differiscono dalle prove KL precedenti.

## Verifiche su MCU

MCU è restituito `optimal`; la funzione obiettivo è finita e i controlli indipendenti registrano **zero celle di vincolo oltre tolleranza**. Non è stata necessaria una pulizia manuale per accettarlo.

Il massimo residuo del modello è circa **0.887834 USD**. Il controllo successivo sui **66 settori pendenti** passa: zero violazioni di budget di output, trade o esportazioni del produttore, zero gruppi incompleti e zero output mancanti. I target del workbook rimanente coincidono con il piano iniziale, salvo il normale arrotondamento della serializzazione Excel.

La riaggregazione diretta del database pubblicato al database di partenza dà questi scarti massimi per cella:

| Matrice | Massimo scarto, USD |
|---|---:|
| Z | 0.004322863 |
| Y | 0.000029104 |
| V | 0.000029104 |
| X | 0.000000000 |
| EY | 0.000000000 |
| VY | 0.000000000 |

La contabilità è verificata secondo `accounting="inherit"`: gli scostamenti di colonna già presenti nella baseline sono ereditati, non eliminati. Non significa che ogni bilancio della baseline sia stato ricondotto a zero. E è esplicitamente differita; EY e VY restano preservate.

## Perché COB si ferma

Entrambi i tentativi COB superano il controllo preliminare affine con Gurobi e il preflight sui budget. L'algoritmo barrier del problema quadratico termina però con `Numerical trouble encountered`, e CVXPY solleva `SolverError`. Il controllo affine usa tolleranze e una piccola banda numerica; non certifica la fattibilità matematica esatta né l'accuratezza della successiva ottimizzazione quadratica. Il messaggio numerico, da solo, non dimostra infeasibilità.

Dopo il primo errore è stato effettuato **un solo tentativo mirato**, cambiando esclusivamente `NumericFocus` da 1 a 3. Gurobi documenta questo parametro come controllo della prudenza dei calcoli numerici: [documentazione ufficiale](https://docs.gurobi.com/projects/optimizer/en/current/concepts/numericguide/numeric_parameters.html). Le tolleranze di fattibilità/ottimalità e convergenza barrier sono rimaste rispettivamente 1e-9, 1e-9 e 1e-10. I **24 CSV numerici sono identici byte per byte** fra i due tentativi, come registrato in `cob-retry-input-identity.json`.

Il secondo errore non è quindi stato risolto dalla maggiore prudenza numerica. La causa specifica rimane da diagnosticare: non è corretto attribuirla automaticamente a dati non puliti, alla memoria o a una vera infeasibilità. Non è stata scartata una soluzione `optimal` per piccoli negativi: Gurobi non ha restituito uno stato accettato. Non sono stati cambiati obiettivo, solver o target per arrivare a due successi.

## Codice e riproducibilità

I 23 test mirati della pipeline su riconciliazione e budget sono passati. Il percorso `--prepared` è stato inoltre eseguito sui dati reali di questa preparazione. I confronti di HEAD e stato dei worktree confermano nessuna nuova modifica in MARIO e CVXLab durante la prova.

- Database MCU e checkpoint riprendibile: `/Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Database/D2.8/20261028 1045 - 49 regions and 1 sectors`.
- Input abbinati: `/Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Inventories/D2.8 inventories/20261028 1045 - 49 regions and 1 sectors`.
- Lavoro locale e comandi completi nei record delle risorse: `/Users/lorenzorinaldi/Documents/GitHub/Database disaggregation/.worktrees/mrio-memory/build/model_trials/20261028_qp49_two_steps_01`.

`diagnostics/future_budgets.json` registra il controllo dei 66 settori futuri. `diagnostics/trade_reconciliation/` contiene la preparazione e l'audit dei trade. `diagnostics/exact_trial_inputs.zip` conserva gli Excel esatti del primo passo e del piano fisso, verificati con hash. `diagnostics/attempts/COB_NumericFocus1/` e `COB_NumericFocus3/` conservano log, input compilato esatto, parametri, fattibilità preliminare e manifest dei due errori.

Il database pubblicato è stato ricaricato con MARIO verificando i checksum, le 49 regioni, i 77 settori totali e MCU come unico settore completato. Gli inventari pubblicati contengono anche i 66 settori pendenti: il loro piano `Remaining sectors` è un segnaposto e va suddiviso prima di proseguire; non va eseguito come un unico grande passo. Nessun terzo settore è stato tentato.
