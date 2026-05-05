# NurisHackathon6.0 — извлечение объектов и признаков с GeoTIFF снимков

Прототип по ТЗ: автоматическое выделение зданий, машин и наземного покрытия
по космическим/аэро-снимкам с экспортом в ГИС-форматы (GeoJSON + GeoPackage).

## Классы и подходы

| Класс | Геометрия | Метод |
|---|---|---|
| `house`, `apartment_block`, `school`, `hospital`, `religious`, `civic`, `commercial`, `industrial`, `outbuilding`, `agricultural` | Polygon | **U-Net (EfficientNet-B0)** обучен на Overture Maps. Под-классификация по тегам Overture + площади footprint. Полигоны выпрямляются ortho-snap'ом. |
| `vegetation`, `bare_soil` | Polygon | Rule-based: ансамбль RGB-индексов (ExG + CIVE + VIg + v) для растительности; DSBI для грунта. **С приоритетом «здание > земля»** при объединении. |
| `car` | Point | Pretrained YOLOv8-OBB (DOTA-v1) — `small vehicle` + `large vehicle` классы. |

Все 20 GeoTIFF: 10 в Алматы (~5.4 см/пиксель) + 10 в Астане (~4.7 см/пиксель).
Из них **4 hold-out сцены** не участвуют в обучении и используются для test-метрик.

## Структура проекта

```
.
├── Almaty/, Astana/                — исходные GeoTIFF (10 + 10 = 20 сцен)
├── aoi/
│   ├── scenes.geojson              — 20 footprint'ов сцен (поле split: train/holdout)
│   ├── summary.csv                 — размеры, разрешение, площади
│   └── overture/
│       ├── buildings_<city>.geojson         — Overture, со сдвигом
│       ├── buildings_<city>_raw.geojson     — Overture без сдвига (backup)
│       └── buildings_clipped.geojson        — Overture внутри AOI
├── scripts/                        — нумерация совпадает с порядком запуска
│   ├── 01_generate_aoi.py          — AOI footprints из GeoTIFF (+ split)
│   ├── 02_download_overture.py     — Overture + tuned alignment shift
│   ├── 02b_finetune_shift.py       — утилита: grid-search сдвига
│   ├── 03_clip_overture_to_aoi.py  — обрезка Overture по AOI
│   ├── 04_extract_segments.py      — SLIC сегменты для landcover (vegetation+soil)
│   ├── 05_train_unet.py            — обучение U-Net (ResNet-34) на Overture-метках
│   ├── 06_predict_unet.py          — инференс U-Net + ortho-snap + sub-class
│   ├── 07_run_yolo_cars.py         — YOLOv8-OBB детекция машин
│   ├── 08_finalize_outputs.py      — TZ-compliant GeoJSON + GeoPackage + summary
│   └── 09_evaluate_holdout.py      — object-level метрики на 4 hold-out
├── src/
│   ├── io/{raster,vector}.py       — чтение GeoTIFF, TZ-схема экспорта
│   ├── tile.py                     — оконный тайлинг растра
│   ├── features/
│   │   ├── masks.py                — RGB-индексы для landcover
│   │   ├── segmentation.py         — SLIC обёртка
│   │   └── segment_features.py     — фичи для landcover
│   ├── labeling.py                 — Overture overlap labelling сегментов
│   ├── pipeline.py                 — per-scene SLIC + features + labelling
│   ├── postprocess/
│   │   ├── ortho_snap.py           — выпрямление углов полигонов
│   │   └── subclassify.py          — Overture tag → 1 из 9 классов
│   ├── unet/
│   │   ├── dataset.py              — PyTorch Dataset (RGB + Overture mask)
│   │   ├── model.py                — smp.Unet + EfficientNet-B0 + Dice/BCE
│   │   ├── train.py                — training loop с MPS
│   │   └── predict.py              — sliding window inference
│   └── logging_config.py           — единый logger для всех скриптов
├── outputs/
│   ├── geojson/                    — все TZ-compliant слои (см. ниже)
│   ├── results.gpkg                — multi-layer для QGIS
│   ├── scene_metrics.csv           — TZ §4.2 метрики по 20 сценам
│   ├── holdout_metrics.csv         — pixel-level test метрики
│   ├── shift_finetune_2d.csv       — таблица 256 пар сдвига
│   ├── models/
│   │   ├── unet_best.pt            — лучший чекпойнт (по val F1)
│   │   └── unet_last.pt            — последний эпохой
│   ├── segments/                   — SLIC-данные для landcover (parquet+geojson)
│   └── logs/                       — логи всех скриптов
├── docs/INSIGHTS.md                — анализ "зачем это сделано"
├── requirements.txt                — Python зависимости
├── run_pipeline.sh                 — однокомандный re-run всего пайплайна
└── README.md                       — этот файл
```

## Структура `outputs/geojson/` (TZ §5)

Все файлы в EPSG:4326. Атрибутивная схема каждой записи:
`id | class | confidence | source | area_m2 | length_m | date | change_flag | geometry`

```
outputs/geojson/
├── <scene>_buildings.geojson      — здания per-scene (20 файлов)
├── <scene>_cars.geojson           — машины per-scene (20)
├── <scene>_landcover.geojson      — растительность + грунт per-scene (20)
├── building_house.geojson         — все дома, объединено по 20 сценам
├── building_apartment_block.geojson
├── building_school.geojson
├── building_hospital.geojson
├── building_religious.geojson
├── building_civic.geojson
├── building_commercial.geojson
├── building_industrial.geojson
├── building_outbuilding.geojson
├── landcover_vegetation.geojson
├── landcover_bare_soil.geojson
├── cars.geojson                   — все машины
├── all.geojson                    — всё в одном FeatureCollection
├── buildings_summary.csv          — per-scene метрики зданий
├── cars_summary.csv
└── landcover_summary.csv
```

## Запуск

```bash
# 1. Установка зависимостей
pip install -r requirements.txt

# 2. Однокомандный полный пайплайн (~80 минут на M4 Pro)
bash run_pipeline.sh
```

Или пошагово:

```bash
# Подготовка данных (~5 мин)
python scripts/01_generate_aoi.py            # AOI + train/holdout split
python scripts/02_download_overture.py       # Overture + tuned shift
python scripts/03_clip_overture_to_aoi.py    # обрезка по AOI

# Базовый SLIC для landcover (~80 мин)
python scripts/04_extract_segments.py

# Обучение U-Net (~1-2 hr на M4 Pro MPS)
python scripts/05_train_unet.py --epochs 15 --encoder resnet34

# Инференс + ortho-snap (~10 мин) и машины (~20 мин)
python scripts/06_predict_unet.py --encoder resnet34
python scripts/07_run_yolo_cars.py

# Финализация + метрики
python scripts/08_finalize_outputs.py
python scripts/09_evaluate_holdout.py
```

## Test метрики

Object-level метрики на 4 hold-out сценах (Almaty_1, Almaty_4, Astana_2, Astana_4),
которые модель не видела при обучении. Эталон — Overture Maps Foundation.

«Any-intersection»: предсказанный полигон считается совпавшим с эталонным,
если их геометрии пересекаются хотя бы в одной точке. Метрика отражает
вопрос: *«нашла ли модель это здание?»*.

См. `outputs/holdout_metrics.csv` (актуальные значения после последнего запуска).

## Ограничения и условия применимости

1. **Источник снимков:** SAS.Planet, дата съёмки в метаданных отсутствует.
   `date` в выдаче = дата проекта, не реальная дата захвата.
2. **RGB-only:** нет NIR-канала, поэтому растительность определяется по
   RGB-индексам (Marcial-Pablo et al. 2019: ~85% accuracy на UAV-RGB).
3. **Эталон Overture:** ML-derived from satellite imagery, имеет систематический
   сдвиг ~3.7 м по lat / 1.2 м по lon относительно нашей подложки;
   это сдвиг скомпенсирован в `02_download_overture.py` после grid-search'а.
4. **Под-классификация:** house vs apartment_block разделяется по
   1) тегу `building` Overture, 2) `building:levels`, 3) площади footprint
   (порог 250 м²). 9 классов всего: house, apartment_block, school, hospital,
   religious, civic, commercial, industrial, outbuilding, agricultural.
5. **Машины — снимок одного момента**, не «трафик». Для оценки трафика
   нужна серия снимков (TZ §4.2 поддерживает это через change_flag).
6. **Recall зависит от плотности застройки.** В частном секторе с густыми
   деревьями (Astana_9, Almaty_5) recall ниже из-за occlusion.
