# Province ID Generator

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Fast](https://img.shields.io/badge/performance-ultra--fast-orange)

Fast OpenCV-based tool for converting color-coded mask maps into province ID maps with JSON metadata. Optimized for large strategy game maps (Paradox style, 4X) using connected component labeling and LUT-based color encoding.

Быстрый инструмент на основе OpenCV для преобразования карт с цветовой кодировкой в ​​карты с идентификаторами провинций и метаданными в формате JSON. Оптимизирован для больших карт стратегических игр (в стиле Paradox, 4X) с использованием маркировки связанных компонентов и цветовой кодировки на основе таблиц поиска (LUT).

---

## Technical Overview / Техническое описание

The generator processes a three-color mask to segment landmasses into discrete regions. Each region is assigned a persistent integer ID, encoded into the RGB channels of the output map.
Инструмент обрабатывает трехцветную маску для сегментации суши на отдельные области. Каждой области присваивается уникальный целочисленный ID, закодированный в RGB-каналы выходной карты.

### ID Encoding Specification / Спецификация кодирования
IDs are mapped to colors using bitwise shifts:
ID сопоставляются с цветами с помощью битовых сдвигов:
$$ID = (R \ll 16) \lor (G \ll 8) \lor B$$
This allows for the unique identification of up to 16,777,215 individual provinces.
Это позволяет идентифицировать до 16 777 215 уникальных провинций.

---

## Performance Benchmarks / Показатели производительности

Testing conducted on a 5616×3000 (16.8 MP) source image (~4,600 provinces):
Тестирование проводилось на исходном изображении 5616×3000 (16.8 Мп), содержащем ~4600 провинций:

| Task / Задача | Execution Time / Время выполнения |
| :--- | :--- |
| Connected Components Labeling | 0.642s |
| LUT-based Color Painting | 0.896s |
| Metadata Synthesis (JSON) | 0.026s |
| I/O Operations (File Saving) | 0.735s |
| **Total Runtime / Итого** | **2.300s** |

---

## Installation / Установка

The tool requires Python 3.10+ and the following dependencies:
Для работы требуется Python 3.10+ и следующие зависимости:

```bash
pip install numpy opencv-python Pillow
