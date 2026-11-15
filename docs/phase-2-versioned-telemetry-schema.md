# Esquema de telemetría sintética v1.0

## Objetivo y límites

Este contrato define las muestras sintéticas Freesun/NB para el simulador y la
evaluación del proyecto. La cadencia inicial de **1 Hz (1000 ms)** es una
decisión configurable para esta demo; **no** se presenta como un estándar
universal de SCADA ni representa la adquisición de formas de onda de
conmutación. Las señales derivadas de mediciones de mayor frecuencia, como
THDi, se consideran lecturas agregadas de un monitor.

Los valores y umbrales de ejemplo son ilustrativos. No son límites de seguridad
ni parámetros calibrados para un equipo real.

## Separación de datos y prevención de fuga

No se almacenan las etiquetas junto con las muestras que se entregan al modelo
o a los agentes. Se generan dos artefactos independientes, relacionados por
`run_id`, `asset_id` y `timestamp`:

1. **Telemetría (`telemetry.jsonl`):** metadatos operativos permitidos,
   señales observables y, opcionalmente, características derivadas. Es la
   única fuente para el pipeline de inferencia.
2. **Etiquetas (`labels.jsonl`):** valores físicos internos del simulador,
   modo/estado de degradación e información del fallo futuro. Solo se usa para
   generar objetivos de entrenamiento y medir resultados; nunca se envía al
   modelo ni al agente.

La asignación `train`/`validation`/`test` vive en un manifiesto del conjunto de
datos, a nivel de ejecución (`run_id`), no en cada muestra. Todas las ventanas
de una ejecución pertenecen a la misma partición. `scenario`, `seed`, las
etiquetas y el manifiesto no forman parte del payload de inferencia.

El modelo recibe una lista permitida de campos de `telemetry.jsonl`, no un
objeto genérico que se limpie eliminando claves prohibidas. Los tests del
pipeline deben comprobar que los artefactos de etiquetas no pueden leerse
desde la ruta de inferencia.

## Cadencia, valores ausentes y calidad

- La cadencia objetivo es de 1000 ms y puede configurarse por ejecución. Cada
  ejecución registra su cadencia en el manifiesto.
- Una medición ausente se representa como JSON `null`, nunca como `NaN`.
  `quality.missing_fields` enumera las señales ausentes en esa muestra.
- `null` en una señal que no aplica al perfil indica “no aplicable”; una señal
  aplicable ausente debe aparecer en `missing_fields`. La máscara de calidad
  permite distinguir ambos casos.
- La imputación se hace en preprocesamiento convencional y solo con datos
  disponibles hasta ese instante: *forward-fill* hasta un máximo configurable;
  si se supera, se marca la muestra como no válida para inferencia. No se usa
  interpolación con muestras futuras en inferencia en línea.
- Las etiquetas de escenarios sintéticos completos no se omiten. `null` en
  `failure_time_utc` significa que la ejecución no contiene un fallo dentro de
  su horizonte simulado, no una etiqueta perdida.

## Contrato de la muestra de telemetría

Cada línea de `telemetry.jsonl` es un objeto JSON independiente y válido.

| Campo | Tipo | Unidad/formato | Uso |
| --- | --- | --- | --- |
| `schema_version` | string | SemVer, inicialmente `1.0.0` | Versión del contrato. |
| `run_id` | string | UUID v4 | Identificador de la ejecución sintética. |
| `sample_index` | entero | Sin unidad | Índice desde cero, monótono dentro de la ejecución. |
| `timestamp` | string | ISO 8601 UTC | Instante de la muestra, con sufijo `Z`. |
| `asset_id` | string | — | Identificador sintético del activo. |
| `profile` | enum | `solar_utility` / `ev_nb` | Perfil operativo; contexto permitido, no etiqueta de degradación. |
| `observables.env_temp_c` | número o `null` | °C | Temperatura ambiente. |
| `observables.relative_humidity_pct` | número o `null` | % | Humedad relativa; entrada ambiental del escenario dieléctrico. |
| `observables.irradiance_w_m2` | número o `null` | W/m² | Irradiancia; aplicable a `solar_utility`. |
| `observables.ev_session_active` | booleano o `null` | — | Sesión de carga; aplicable a `ev_nb`. |
| `observables.ev_power_kw` | número o `null` | kW | Potencia entregada al vehículo; aplicable a `ev_nb`. |
| `observables.heatsink_temp_c` | número o `null` | °C | Temperatura medida del disipador. |
| `observables.dc_bus_voltage_v` | número o `null` | V | Tensión del bus DC. |
| `observables.dc_bus_current_a` | número o `null` | A | Corriente del bus DC. |
| `observables.ac_current_l1_a` | número o `null` | A | Corriente AC de fase L1. |
| `observables.ac_current_l2_a` | número o `null` | A | Corriente AC de fase L2. |
| `observables.ac_current_l3_a` | número o `null` | A | Corriente AC de fase L3. |
| `observables.dc_link_esr_est_mohm` | número o `null` | mΩ | Estimación proporcionada por un monitor; no es la ESR interna exacta. |
| `observables.insulation_resistance_est_megaohm` | número o `null` | MΩ | Estimación proporcionada por un monitor. |
| `observables.thdi_pct` | número o `null` | % | THDi agregada informada por un monitor. |
| `observables.thermal_derating_active` | booleano o `null` | — | Estado informado por el controlador; no se infiere solo con temperatura ambiente. |
| `features.ac_current_imbalance_pct` | número o `null` | % | Máxima desviación absoluta de las corrientes de fase respecto a su media, dividida por esa media y multiplicada por 100. |
| `quality.missing_fields` | lista de strings | Rutas de campos | Señales aplicables ausentes en la muestra. |

Las señales de irradiancia y carga EV son específicas de cada perfil; se usan
como `null` cuando no aplican. El porcentaje de asimetría usa la definición
`max(abs(I_fase - media(I_fases))) / media(I_fases) * 100`; no se supone que el
dispositivo lo mida directamente. Las ventanas de entrenamiento se forman
después de dividir las ejecuciones, nunca antes.

## Contrato de etiquetas separado

Cada línea de `labels.jsonl` corresponde a una muestra de telemetría por
`run_id`, `asset_id` y `timestamp`.

| Campo | Tipo | Unidad/formato | Uso |
| --- | --- | --- | --- |
| `run_id`, `asset_id`, `timestamp` | Igual que la telemetría | — | Clave para evaluación; no son entradas de modelo. |
| `ground_truth.junction_temp_c` | número | °C | Temperatura de unión generada por el modelo térmico del simulador. |
| `ground_truth.dc_link_esr_mohm` | número | mΩ | ESR interna exacta generada por el simulador. |
| `ground_truth.insulation_resistance_megaohm` | número | MΩ | Resistencia interna generada por el simulador. |
| `ground_truth.degradation_mode` | enum | — | `none`, `igbt_thermal_fatigue`, `dc_link_capacitor` o `insulation`; puede ampliarse en una nueva versión. |
| `ground_truth.degradation_state` | enum | — | `healthy`, `early_warning` o `critical`, según umbrales documentados en la configuración del escenario. |
| `ground_truth.event_onset_utc` | timestamp o `null` | ISO 8601 UTC | Inicio de la degradación; `null` si el escenario es sano. |
| `ground_truth.failure_time_utc` | timestamp o `null` | ISO 8601 UTC | Instante de fallo simulado; `null` si no ocurre durante la ejecución. |
| `ground_truth.failure_within_horizon` | booleano o `null` | — | Si el fallo ocurre dentro de `prediction_horizon_s` configurado para la ejecución. `null` si la etiqueta no aplica. |

Los umbrales de temperatura, ESR y aislamiento se configuran por escenario y
se guardan en el manifiesto; no son constantes universales del esquema. El
estado de degradación describe el estado actual simulado. La predicción de un
fallo dentro de un horizonte fijo es un objetivo distinto, calculado a partir
de `failure_time_utc`; no se confunde con una alarma por umbral instantáneo.
Si se entrena una predicción futura de ESR, temperatura o aislamiento, el
objetivo debe desplazarse al horizonte definido y no copiar la etiqueta del
mismo instante.

## Manifiesto de ejecución y particiones

El manifiesto, fuera de las muestras y de la ruta de inferencia, registra:

- `run_id`, `seed`, `profile`, `scenario` y `schema_version`;
- `sampling_period_ms`, `prediction_horizon_s` y duración de la ejecución;
- grupo de evaluación (`train`, `validation` o `test`), asignado por ejecución;
- configuración y umbrales usados para generar etiquetas.

No se reutiliza el mismo `run_id` entre particiones. La misma semilla y
configuración deben reproducir la ejecución, sin compartir ventanas
solapadas entre conjuntos.

## Ejemplos JSON válidos

### Muestra observable sana (perfil solar)

```json
{
  "schema_version": "1.0.0",
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "sample_index": 0,
  "timestamp": "2026-11-15T12:00:00.000Z",
  "asset_id": "FREESUN-HEC-01",
  "profile": "solar_utility",
  "observables": {
    "env_temp_c": 28.5,
    "relative_humidity_pct": 52.0,
    "irradiance_w_m2": 900.0,
    "ev_session_active": null,
    "ev_power_kw": null,
    "heatsink_temp_c": 52.1,
    "dc_bus_voltage_v": 1450.0,
    "dc_bus_current_a": 700.0,
    "ac_current_l1_a": 800.2,
    "ac_current_l2_a": 801.0,
    "ac_current_l3_a": 799.5,
    "dc_link_esr_est_mohm": 15.2,
    "insulation_resistance_est_megaohm": 24.0,
    "thdi_pct": 1.2,
    "thermal_derating_active": false
  },
  "features": {
    "ac_current_imbalance_pct": 0.10
  },
  "quality": {
    "missing_fields": []
  }
}
```

La etiqueta asociada se almacena en `labels.jsonl`, nunca en el objeto anterior:

```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "asset_id": "FREESUN-HEC-01",
  "timestamp": "2026-11-15T12:00:00.000Z",
  "ground_truth": {
    "junction_temp_c": 82.5,
    "dc_link_esr_mohm": 15.2,
    "insulation_resistance_megaohm": 25.0,
    "degradation_mode": "none",
    "degradation_state": "healthy",
    "event_onset_utc": null,
    "failure_time_utc": null,
    "failure_within_horizon": false
  }
}
```

### Muestra observable con anomalía térmica incipiente (perfil solar)

```json
{
  "schema_version": "1.0.0",
  "run_id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
  "sample_index": 13500,
  "timestamp": "2026-11-15T13:45:00.000Z",
  "asset_id": "FREESUN-HEC-01",
  "profile": "solar_utility",
  "observables": {
    "env_temp_c": 30.2,
    "relative_humidity_pct": 48.0,
    "irradiance_w_m2": 850.0,
    "ev_session_active": null,
    "ev_power_kw": null,
    "heatsink_temp_c": 68.4,
    "dc_bus_voltage_v": 1450.0,
    "dc_bus_current_a": 650.0,
    "ac_current_l1_a": 710.0,
    "ac_current_l2_a": 745.5,
    "ac_current_l3_a": 748.2,
    "dc_link_esr_est_mohm": 16.8,
    "insulation_resistance_est_megaohm": 23.8,
    "thdi_pct": 2.8,
    "thermal_derating_active": false
  },
  "features": {
    "ac_current_imbalance_pct": 3.34
  },
  "quality": {
    "missing_fields": []
  }
}
```

En esta muestra la temperatura interna de unión **no** se incluye en la
telemetría entregada al modelo. El valor interno y las etiquetas de pronóstico
se guardan únicamente en el artefacto de etiquetas.

## Pruebas de conformidad requeridas

Antes de cerrar la issue #2, validar automáticamente que:

1. Los dos ejemplos se pueden parsear como JSON estricto y respetan el esquema.
2. Los identificadores son UUID válidos y las marcas temporales son UTC.
3. Las señales ausentes usan `null` y aparecen en `quality.missing_fields`;
   nunca se serializan `NaN` o infinitos.
4. La entrada del predictor solo contiene campos permitidos de telemetría y
   no puede acceder a `labels.jsonl`, `ground_truth`, `scenario`, `seed` ni
   `eval_group`.
5. Las particiones se asignan por ejecución antes de crear ventanas.
6. La selección de características y las etiquetas no dependen de muestras
   futuras en el flujo de inferencia en línea.
