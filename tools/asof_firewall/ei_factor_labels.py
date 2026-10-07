
from __future__ import annotations

from typing import Iterable


INDUSTRY_LABELS = {
    "交通运输": "Transportation",
    "传媒": "Media",
    "公用事业": "Utilities",
    "农林牧渔": "Agriculture",
    "医药生物": "Pharmaceuticals and Biotechnology",
    "商贸零售": "Retail",
    "国防军工": "Defense",
    "基础化工": "Basic Chemicals",
    "家用电器": "Home Appliances",
    "建筑材料": "Building Materials",
    "建筑装饰": "Construction",
    "房地产": "Real Estate",
    "有色金属": "Nonferrous Metals",
    "机械设备": "Machinery",
    "汽车": "Automobiles",
    "煤炭": "Coal",
    "环保": "Environmental Services",
    "电力设备": "Electrical Equipment",
    "电子": "Electronics",
    "石油石化": "Petroleum and Petrochemicals",
    "社会服务": "Social Services",
    "纺织服饰": "Textiles and Apparel",
    "综合": "Conglomerates",
    "美容护理": "Beauty and Personal Care",
    "计算机": "Computers",
    "轻工制造": "Light Manufacturing",
    "通信": "Telecommunications",
    "钢铁": "Steel",
    "银行": "Banking",
    "非银金融": "Nonbank Financials",
    "食品饮料": "Food and Beverages",
}


def english_factor_labels(labels: Iterable[object]) -> list[str]:
    translated = []
    for label in labels:
        name = str(label)
        if not name.isascii() and name not in INDUSTRY_LABELS:
            raise ValueError(f"Unknown non-English risk factor: {name!r}")
        translated.append(INDUSTRY_LABELS.get(name, name))
    if len(translated) != len(set(translated)):
        raise ValueError("Risk factor names are not unique after translation")
    return translated
