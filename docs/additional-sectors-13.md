# Estensione del database ENTICE a 13 regioni — 28 ottobre 2026

Il database risultante contiene **69 attività ENTICE disaggregate e 145 settori totali**. La sequenza PCP → BAR → SGI ha concluso tutti e tre gli step con stato Gurobi `optimal`. Gli output delle 66 attività già presenti e mantenute sono identici a quelli del database precedente. I file originali sono intatti.

## Perimetro e conteggio

Il punto di partenza è `20261021 0655 - 13 regions and 67 sectors`: 67 attività ENTICE oltre alle 76 categorie GTAP. Si mantengono 66 attività, si ricostruisce PCP e si aggiungono BAR e SGI. Il conteggio passa quindi da 67 a 69, non a 70.

| Codice | Attività | Trattamento |
|---|---|---|
| BAR | Cultivation of barley | Nuova attività nel parent GRO |
| SGI | Manufacture of steel via BF-BOF with natural gas injection | Nuova attività nel parent I_S |
| PCP | Coal products | Ricostruzione dell'attività esistente con il template sui prodotti del carbone |
| P_C | Petroleum products | Residuo della famiglia petroleum/coal dopo la ricostruzione di PCP |

AMM, HYS e una nuova estrazione di silicio sono esclusi per decisione del proprietario. MSI, il silicio metallurgico già presente, resta incluso e invariato nella classificazione. Non vengono introdotti proxy per AMM o HYS.

**Petroleum products e crude-oil extraction sono attività diverse.** La distinzione coal/petroleum è applicata alla famiglia P_C. OIL, l'estrazione di petrolio greggio, conserva il suo identificativo e il suo significato. Non si aggiunge un terzo settore sovrapposto a PCP. Il nuovo PCP ha un perimetro più ampio del precedente coke: non è una semplice rinomina di quel vecchio risultato.

## Come si riparte senza rifare le 66 attività

PCP viene riaggregato a P_C, sommando le righe e le colonne interessate in tutti i flussi. L'output X indipendente viene aggregato allo stesso modo e allineato agli indici di Z. Si ottiene una baseline importata di 142 settori, sulla quale aggiungere di nuovo PCP, poi BAR, poi SGI, uno alla volta.

Questo è un nuovo ciclo di calcolo sopra un database esistente. I metadati distinguono le 66 attività storiche dai tre step effettivamente eseguiti: non attribuiscono ai vecchi risultati la formulazione, la revisione del codice o il solver della nuova prova. `baseline-provenance.json` conserva la provenienza.

## Dati e assunzioni di preparazione

**Produzione.** Si leggono le colonne monetarie 2023 dei template raccolti: G/H per BAR e PCP, E/F per SGI. Dove mancano osservazioni si applica la regola già in uso di trasferimento della quota figlio/parent. La stima utilizza la geografia nativa; il controllo finale delle capacità utilizza il parent residuo effettivamente disponibile nel database a 13 regioni. In questa prova non è stato necessario ridurre alcun output con un cap.

**Geografia di BAR.** Alcuni paesi osservati appartengono a regioni residuali di GTAP. La nuova configurazione riporta esplicitamente appartenenza e fonte delle corrispondenze. I valori vengono sommati una sola volta. Una copertura completa del residuo può essere trattata come osservazione diretta; una copertura parziale rimane un'informazione debole, con peso 0,1, e non viene presentata come totale osservato dell'intera regione. Un totale nativo già disponibile prevale sulle sue componenti, evitando doppi conteggi. Le osservazioni parziali e gli scarti del raccordo restano nell'audit.

**Profili tecnici.** Si leggono i coefficienti monetari originali, anche quando la somma non è esattamente uno. Prima veniva scartato il profilo SGI perché somma a **0,9972469214**: ora viene conservato e riconciliato con la stessa proiezione monetaria già usata dalla pipeline. Le righe dei fattori con segno e le componenti ambientali seguono le regole esistenti. I profili disponibili sono 40 per PCP, 18 per BAR e **uno per SGI, relativo agli USA**. Il profilo SGI viene quindi trasferito agli altri paesi: è una limitazione informativa rilevante, non una tecnologia osservata ovunque. Per BAR un profilo nazionale prevale su un gruppo sovrapposto; in assenza di un profilo proprio si usano donatori della stessa attività nella macroregione e poi nel mondo.

**Settori di input.** Un nome che individua esplicitamente un'attività ENTICE viene collegato a quella attività. Una categoria GTAP ampia viene interpretata come la sua famiglia, includendo i figli già presenti, invece di assegnarla tutta al solo residuo post-split. La ripartizione interna usa le regole esistenti e resta un prior. Non costituisce un'osservazione sui singoli componenti e non misura rapporti tecnologici fra tutte le attività future.

**Trade.** Per questi tre casi il commercio viene stimato dal pattern del parent corrente moltiplicato per la quota di output del figlio, con limite alle esportazioni totali dato dall'output. Tutte le rotte estere, anche quelle a zero, sono esplicite per proteggere i budget dei passaggi successivi. Sono prior stimati, non target indipendenti di Comtrade. Il file e l'audit li dichiarano tali.

Il template SGI presenta anche un'intestazione generale che menziona coke injection, mentre nome del file e nota metodologica del processo descrivono natural-gas injection. L'associazione è esplicita nella configurazione; la discrepanza della fonte resta da chiarire in una revisione economica.

## Modello e solver

La prova usa l'attuale modello **quadratico con Gurobi**, nella pipeline MARIO → CVXLab: `accounting="inherit"`, peso Y 0,1, peso supply 1, scala 1000, vincoli compatti e verifica di fattibilità con Gurobi. Non viene introdotta una nuova formulazione e non viene modificato CVXLab. Il nome del modello è `Split_sectors_MRIO_quadratic`.

Il primo tentativo PCP, con FeasibilityTol/OptimalityTol 1e-9 e BarConvTol 1e-10, ha restituito un esito non ottimale (`user_limit` nell'interfaccia CVXPY). Il limite temporale non era stato consumato. È stato eseguito **un solo nuovo tentativo**, usando le tolleranze standard del Gurobi installato: FeasibilityTol/OptimalityTol **1e-6**, BarConvTol **1e-8**. Restano Threads=2, NumericFocus=1 e NonConvex=0; TimeLimit passa da 1800 a 600 secondi, OutputFlag da 0 a 1. I **24 CSV numerici di input PCP sono identici** fra i due tentativi. Il secondo tentativo ha completato tutti e tre gli step; non sono state cambiate le osservazioni per farlo convergere.

| Step | Stato | Tempo solver | Max scarto Z riaggregata dello step | Max violazione dei vincoli | Celle cambiate dal post-processing |
|---|---|---:|---:|---:|---:|
| PCP | optimal | 0.355 s | 49.05 USD | 970.71 USD | 0 |
| BAR | optimal | 0.364 s | 79.66 USD | 937.78 USD | 0 |
| SGI | optimal | 0.214 s | 22.58 USD | 260.61 USD | 0 |

I due indicatori di scarto misurano cose diverse: la prima colonna confronta le celle riaggregate con la baseline dello step, la seconda considera tutti i vincoli del modello. Sono riportati in **USD**, dopo aver rimosso la scala interna. Le soluzioni `optimal` vengono conservate con la diagnostica monetaria, senza un rifiuto automatico legato a questi scarti. In questi tre step il post-processing dei domini non ha modificato nessuna cella restituita dal solver.

## Controllo cumulativo e risorse

Riaggregando PCP, BAR e SGI alla baseline importata di 142 settori, il massimo scostamento è **79,66 USD per cella in Z**, **6,76 USD in Y**, meno di 0,001 USD in V e solo arrotondamento macchina in X. La somma dei valori assoluti degli scarti è circa **701,50 USD in Z** e **16,33 USD in Y**. Gli output delle 66 attività mantenute dal database precedente sono esattamente invariati. Gli squilibri ereditati dalla baseline sono distinti dagli scarti introdotti dal nuovo calcolo.

La sequenza completa, inclusi costruzione, interfaccia ed esportazione dei checkpoint, ha richiesto **56.5 secondi** nel processo monitorato; il tempo registrato dal runner è 52.9 secondi. Il picco misurato di physical footprint del processo e dei figli è **0.69 GiB**; il picco RSS è 2.04 GiB. Queste misure riguardano tre aggiunte sequenziali a 13 regioni e non stimano una risoluzione simultanea di tutti i settori o il caso a 49/163 regioni.

## Nomi, input cumulativi e verifica dei file

Le etichette dei parent effettivamente presenti nelle matrici diventano **Rest of + descrizione originale**, salvo P_C → Petroleum products. PCP diventa Coal products. I file `sector_classification.csv`, `sector_names.json` e `state.json` conservano una corrispondenza reversibile fra codici di calcolo e nomi esportati. Il loader della pipeline ripristina i codici per continuare i calcoli; anche la lettura numerica per i benchmark normalizza i nomi. La rinomina non cambia alcun valore.

Il file cumulativo `add_sectors.xlsx` contiene **69 attività × 13 regioni = 897 profili**, inclusi quelli storici. Il gruppo Historical sectors è una raccolta di riferimento dei 66 input mantenuti, non un'affermazione che siano stati risolti insieme in questa prova. `source_add_sectors.xlsx` contiene i tre input di questa continuazione, `step_add_sectors.xlsx` l'ultimo step SGI e `remaining_add_sectors.xlsx` è vuoto perché i tre passaggi sono completati. Gli input esatti storici e dei singoli step sono archiviati in `diagnostics/exact_inputs.zip`.

Sono stati verificati riapertura del database con i nomi, caricamento con i codici, uguaglianza numerica esatta prima/dopo rinomina, integrità del checkpoint originale e dei tre template raccolti. I test mirati della pipeline danno **40 passed, 1 skipped**; il test saltato è opzionale. È stato eseguito anche `--help` del nuovo comando di preparazione. Quel comando riutilizzabile non è stato usato per un'altra run: la prova qui descritta proviene dal driver esatto archiviato in `diagnostics/provenance`.

Le modifiche di questa estensione sono nella repository **Database disaggregation**: preparazione delle attività, opzione di budget residuo, configurazione, nomi reversibili, caricamento e test. Si usano le funzioni MARIO già esistenti di riaggregazione e rinomina. Non sono stati modificati sorgenti MARIO o CVXLab per questa estensione. Le modifiche MARIO precedenti restano quelle della sperimentazione già in corso, con hash nel manifest.

**E deve ancora essere ricalcolata.** Lo stato solver `optimal` e la conservazione contabile non sostituiscono la validazione economica dei nuovi profili, soprattutto dove la tecnologia è trasferita e il trade è stimato. I risultati sono interni al progetto.

## Dove sono i risultati

- Database: `/Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Database/D2.8/20261028 1548 - 13 regions and 69 sectors`
- Inventory: `/Users/lorenzorinaldi/Library/CloudStorage/OneDrive-SharedLibraries-WSPO365/RCD-Entice-EXT - Documents/General/2.Deliverables and Milestones/WP2. Improved data and empirics on trade and climate/Data split/Inventories/D2.8 inventories/20261028 1548 - 13 regions and 69 sectors`
- Diagnostica, audit, input esatti e provenienza: `diagnostics/` nella cartella del database.
- Preparazione locale: `build/model_trials/20261028_additional13_04` nel worktree della pipeline.

Per preparare nuovi file della stessa prova, con i percorsi personali già impostati in `paths.local.json`, dalla radice del worktree:

```bash
python scripts/prepare_additional_sectors.py --output build/additional13-new
```

Questo comando prepara i file e una baseline importata; non avvia ottimizzazioni. Mantiene il perimetro PCP/BAR/SGI in `config/additional-sectors-13.json`, usa una cartella di output nuova e consente `--baseline-run` e `--data-root`. Per l'esecuzione originale, opzioni, comando completo e ambiente sono in `diagnostics/resources-defaults.json`, `model-options.json` e nel manifest incorporato in `run.json`.
