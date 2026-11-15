# Hoja de ruta y plan de demo

## Estimación

**Fecha objetivo de revisión: 15 de enero de 2027.** Es una estimación de
planificación, no una garantía. Supone un desarrollo individual de 8–10 horas
por semana desde el 16 de noviembre de 2026, unas 72–90 horas en total y una
demo de portfolio con datos sintéticos y acciones simuladas. Incluye cerca de
una semana para integración y margen. Revisa la fecha si cambia mucho la
disponibilidad semanal o el acceso a servicios cloud.

| Hito | Fecha objetivo | Criterios de salida |
| --- | --- | --- |
| M1 — Estado del arte y especificación del modelo secuencial | 4 dic 2026 | Informe de Fase 2 incorporado; esquema de telemetría, política acotada de ventanas, protocolo de evaluación y revisión de afirmaciones cuantitativas completados. |
| M2 — Simulador y baseline predictivo | 18 dic 2026 | Telemetría y degradación Freesun/NB reproducibles; baseline evaluado en ejecuciones sintéticas reservadas; modelo disponible mediante una interfaz estable. |
| M3 — Investigación multiagente y acciones seguras | 8 ene 2027 | Orquestación ADK y agentes especialistas usan herramientas tipadas; todas las acciones pasan por una política de bloqueo seguro; las acciones externas siguen simuladas. |
| M4 — Observabilidad y paquete listo para demo | 15 ene 2027 | Escenario integral, visualización, trazas, guía de ejecución, limitaciones y lista de revisión preparados. |

## Resultado de la Fase 2 y decisiones del modelo

El [informe SOTA de la Fase 2](phase-2-sota.md) propone estimar la temperatura
oculta con PINN/LSTM, adaptar ventanas a los perfiles Freesun y NB, modelar la
degradación del aislamiento según la humedad y aplicar métricas de pronóstico.
Son hipótesis de diseño, no resultados validados en equipos reales.

El orden de implementación será deliberadamente más acotado. Consulta las
[decisiones de implementación](phase-2-implementation-notes.md):

1. Definir un contrato de telemetría versionado y separar las entradas
   observables de la verdad-terreno del simulador.
2. Crear perfiles operativos y escenarios de degradación deterministas y
   reproducibles mediante una semilla.
3. Establecer primero un baseline sencillo inspirado en la física; probar LSTM
   después. Añadir PINN, atención u otras arquitecturas solo si los datos y la
   mejora observada justifican su complejidad.
4. Implementar de forma determinista y acotada la selección de régimen y ventana.
   Los agentes investigan eventos detectados; no controlan el muestreo rápido
   ni las protecciones.
5. Tratar el daño por humedad y el rendimiento del modelo como sintéticos y no
   calibrados, salvo que se disponga de parámetros del material y datos de
   validación adecuados.

## Criterios de aceptación de la demo

- Una instrucción documentada, o una secuencia breve, inicia el simulador y la
  aplicación desde un entorno local limpio.
- Una semilla fija reproduce el escenario de degradación elegido.
- La detección y la predicción identifican la señal simulada, el perfil del
  activo, la incertidumbre y el horizonte previsto.
- La evaluación separa cronológicamente entrenamiento, validación y prueba,
  incluye al menos un baseline e informa falsas alarmas y antelación en
  escenarios sintéticos reservados.
- No se presenta la cifra de precisión térmica del informe ni una métrica de
  datos sintéticos como garantía para equipos reales sin reproducirla y
  documentar las condiciones de prueba.
- Las salidas de agentes citan la telemetría y los resultados de herramientas
  utilizados; los esquemas y errores de las herramientas son explícitos.
- Se rechazan las acciones inseguras, mal formadas o no aprobadas. La demo no
  requiere credenciales ni endpoints OT reales.
- El revisor puede seguir un evento desde la telemetría, pasando por la
  predicción, el análisis y la decisión de seguridad, hasta una orden simulada.

## Alcance y controles de riesgo

- El simulador no es un gemelo digital validado; el rendimiento con datos
  sintéticos no demuestra precisión predictiva en producción.
- No conectar la demo a SCADA, inversores, Jira o SAP de producción. Las acciones
  administrativas y de control de potencia son simuladas.
- La integración con Model Armor depende del acceso a Google Cloud; si no está
  disponible, usar un doble de prueba local claramente identificado y
  documentar la limitación.
- Phoenix u otra configuración de trazas local es suficiente; una cuenta
  externa de observabilidad no debe bloquear la demo.
- Priorizar las cuatro señales principales. THDi y derating térmico activo son
  contexto opcional si el calendario lo permite.

## Ritmo de trabajo

Usa el GitHub Project para mover las incidencias por Por hacer, En curso, En
revisión y Hecho. Mantén el desarrollo en `main`. Revisa la fecha objetivo en
cada hito y recorta primero el alcance opcional, no la comprobabilidad ni la
política de seguridad.
