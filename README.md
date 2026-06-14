# 카타르 월드컵은 사막을 어떻게 바꾸었는가?

**2022 FIFA 월드컵 개최에 따른 Lusail(루사일) 지역 도시화 및 녹지 변화 분석**

Landsat Collection 2 Level-2 위성영상을 이용해 2000 / 2010 / 2022년 세 시기를
비교하고, 도시화·녹지·사막 면적 변화를 정량 분석하는 종단 파이프라인입니다.

---

## 1. 설치

```powershell
python -m pip install -r requirements.txt
```

> Windows에서 `rasterio` / `pyproj` 설치가 막히면 다음을 권장합니다.
> ```powershell
> python -m pip install --upgrade pip
> python -m pip install rasterio pyproj --only-binary=:all:
> ```

## 2. 실행

```powershell
python main.py                # 전체 파이프라인 (검색→다운로드→분석→지도→발표자료)
python main.py --skip-download   # 이미 받은 data/processed/*.tif 재사용
python main.py --force           # 강제 재다운로드
```

전체 실행 시 인터넷이 필요합니다 (AWS Earth Search STAC API 조회).
다운로드는 **AOI windowed read** 방식으로, 전체 장면이 아니라 12×12 km 영역만 읽습니다.

## 3. 출력물

```
outputs/
├── maps/
│   ├── rgb_2000.png  rgb_2010.png  rgb_2022.png  rgb_comparison.png
│   ├── ndvi_2000.png / ndbi_/ mndwi_ / bsi_ … (각 시기별)
│   ├── dndvi_2000_2022.png  dndbi_…  dmndwi_…  dbsi_…   (차분영상)
│   ├── landcover_2000.png … landcover_comparison.png
│   └── *.tif   (모든 분석 산출물은 GeoTIFF로도 저장)
├── tables/
│   ├── mean_indices.csv
│   ├── landcover_area.csv
│   ├── change_summary.csv
│   └── transition_2000_2022.csv
├── graphs/
│   ├── bar_landcover.png
│   ├── bar_urban_vs_desert.png
│   └── line_indices.png
└── presentation/
    ├── Lusail_WorldCup_RS_Presentation.pptx   (13 slides + speaker notes)
    └── expected_qa.md                          (예상 Q&A 10문항)
```

## 4. 분석 방법

| 단계 | 산출물 | 목적 |
|---|---|---|
| 1. STAC 검색 | best scene/year | 1~4월 + cloud<10% |
| 2. Windowed read | AOI 6-band stack | UTM 39N 30 m 격자 |
| 3. 지수 | NDVI / NDBI / MNDWI / BSI | 정량 비교 |
| 4. 차분영상 | Δ-pairs (2000→2010, 2010→2022, 2000→2022) | 변화 탐지 |
| 5. KMeans | 5-class land cover | Water / Urban / Veg / Desert / Mixed |
| 6. 전이행렬 | Desert→Urban 등 km² | 가설 검증 |

모든 지도는 **북향 화살표 · 스케일바 · 좌표 그리드(lat/lon) · 범례** 를 포함합니다.

## 5. 디렉토리

```
remote sensing_worldcup/
├── main.py
├── config.py
├── requirements.txt
├── README.md
└── src/
    ├── data_acquisition.py
    ├── indices.py
    ├── classification.py
    ├── change_detection.py
    ├── analysis.py
    ├── mapping.py
    └── presentation.py
```

## 6. 발표 시 답변 가능한 핵심 질문

`outputs/presentation/expected_qa.md` 에 10문항이 한국어 답변과 함께 저장됩니다.
교수 예상 질문(왜 Landsat? 왜 2000/2010/2022? 사막/도시 구분? 면적 계산법? 등) 포함.

## 7. 라이선스 / 데이터 출처

- Landsat Collection 2 Level-2 © USGS (public domain)
- STAC catalog: AWS Earth Search v1 (https://earth-search.aws.element84.com/v1)
