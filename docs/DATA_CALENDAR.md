# 数据更新日历

本页由 `tools/gen_data_calendar.py` 从兄弟仓 `../airflow/data_monitor/stats_config.py` 的 `STATS_CHECKS` 生成（禁止手改）。用途：说明每个数据集**多久没更新算过期**、提前预警阈值与优先级；精确 cron 见 airflow `dag_registry.yaml`。

共 **109** 个监控数据集。`过期阈值` = 最新业务期龄超过即 FAIL（红）；`预警阈值` = 提前降级 WARN（黄）。

## 分组概览

| 分组 | 数据集数 | P0 | P1 | P2 |
|---|---|---|---|---|
| 分红 | 1 | 0 | 1 | 0 |
| 利率 | 1 | 0 | 0 | 1 |
| 同行比较 | 3 | 0 | 3 | 0 |
| 回购 | 1 | 0 | 0 | 1 |
| 宏观 | 81 | 0 | 73 | 8 |
| 并购重组 | 1 | 0 | 0 | 1 |
| 机构持仓 | 3 | 0 | 3 | 0 |
| 沪港通 | 1 | 0 | 0 | 1 |
| 盈利预测 | 2 | 0 | 2 | 0 |
| 股东 | 2 | 0 | 0 | 2 |
| 股本变动 | 1 | 0 | 1 | 0 |
| 财报PDF | 2 | 2 | 0 | 0 |
| 财报三+一 | 8 | 8 | 0 | 0 |
| 质押 | 1 | 0 | 0 | 1 |
| 资本运作 | 1 | 0 | 1 | 0 |

## 数据集明细

| 分组 | 数据集 | 市场 | 集合 | 更新频率 | 过期阈值 | 预警阈值 | 优先级 |
|---|---|---|---|---|---|---|---|
| 财报PDF | 公告PDF | cn | `cn_stock_notice` | 日 | 30 天 | — | P0 |
| 财报PDF | 公告PDF | hk | `hk_stock_notice` | 日 | 30 天 | — | P0 |
| 财报三+一 | 利润表 | cn | `cn_stock_fn_income` | 季（A 股） | 120 天 | — | P0 |
| 财报三+一 | 利润表 | hk | `hk_stock_fn_income` | 季（港股） | 120 天 | — | P0 |
| 财报三+一 | 现金流量表 | cn | `cn_stock_fn_cashflow` | 季（A 股） | 120 天 | — | P0 |
| 财报三+一 | 现金流量表 | hk | `hk_stock_fn_cashflow` | 季（港股） | 120 天 | — | P0 |
| 财报三+一 | 财务指标 | cn | `cn_stock_fn_main` | 季（A 股） | 120 天 | — | P0 |
| 财报三+一 | 财务指标 | hk | `hk_stock_fn_main` | 季（港股） | 120 天 | — | P0 |
| 财报三+一 | 资产负债表 | cn | `cn_stock_fn_balance` | 季（A 股） | 120 天 | — | P0 |
| 财报三+一 | 资产负债表 | hk | `hk_stock_fn_balance` | 季（港股） | 120 天 | — | P0 |
| 分红 | 分红(第三方源) | cn | `cn_stock_dividend_lxr` | 时间戳 | 90 天 | — | P1 |
| 同行比较 | 估值比较 | cn | `cn_stock_thbj_gzbj` | 季（A 股） | 90 天 | — | P1 |
| 同行比较 | 成长性比较 | cn | `cn_stock_thbj_czfx` | 季（A 股） | 90 天 | — | P1 |
| 同行比较 | 杜邦分析 | cn | `cn_stock_thbj_dbfx` | 季（A 股） | 90 天 | — | P1 |
| 宏观 | CCTD动力煤现货价 | cn | `cn_macro_cctd_spot` | 日 | 10 天 | — | P1 |
| 宏观 | CEA碳价日行情 | cn | `cn_macro_cea_daily` | 日 | 10 天 | 3 天 | P1 |
| 宏观 | CLD到岸价日度 | cn | `cn_macro_cld_daily` | 日 | 5 天 | 3 天 | P1 |
| 宏观 | EIA开放数据bulk | cn | `cn_macro_eia_bulk` | 日 | 10 天 | 7 天 | P1 |
| 宏观 | JODI石油 | cn | `cn_macro_jodi_oil` | 月 | 400 天 | — | P1 |
| 宏观 | UPU全球邮政统计 | cn | `cn_macro_postal_upu` | annual | 800 天 | — | P1 |
| 宏观 | USGS矿产展望 | cn | `cn_macro_usgs_outlook` | annual | 800 天 | — | P1 |
| 宏观 | USGS矿产年报 | cn | `cn_macro_usgs_mcs` | annual | 800 天 | — | P1 |
| 宏观 | USGS矿产年鉴抽表 | cn | `cn_macro_usgs_ofr_myb` | annual | 800 天 | — | P1 |
| 宏观 | USGS矿产快报 | cn | `cn_macro_usgs_mis` | weekly | 200 天 | — | P1 |
| 宏观 | USGS矿产概览 | cn | `cn_macro_usgs_mcs_overview` | annual | 800 天 | — | P1 |
| 宏观 | USGS铜快报档案 | cn | `cn_macro_usgs_mis_cu` | weekly | 200 天 | — | P1 |
| 宏观 | USGS铝快报档案 | cn | `cn_macro_usgs_mis_al` | weekly | 200 天 | — | P1 |
| 宏观 | 三峡水库水情 | cn | `cn_cjh_sanxia_water` | 日 | 3 天 | 1 天 | P1 |
| 宏观 | 上海电网代购价 | cn | `cn_macro_power_px_sh_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 乘用车产销 | cn | `cn_macro_cpca_pv` | 月 | 60 天 | — | P1 |
| 宏观 | 云南电网代购价 | cn | `cn_macro_power_px_yn_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 交易所仓单日报 | cn | `cn_macro_futures_receipts` | 日 | 10 天 | 4 天 | P1 |
| 宏观 | 光伏新增装机 | cn | `cn_macro_nea_solar` | quarterly | 180 天 | — | P1 |
| 宏观 | 全社会用电量 | cn | `cn_macro_nea_electricity` | 月 | 60 天 | — | P1 |
| 宏观 | 农产品批发价日报 | cn | `cn_macro_pfsc_farm_daily` | 日 | 10 天 | 3 天 | P1 |
| 宏观 | 北京电网代购价 | cn | `cn_macro_power_px_bj_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 厂商排行 | cn | `cn_macro_cpca_man_rank` | 月 | 60 天 | — | P1 |
| 宏观 | 发电装机 | cn | `cn_macro_nea_capacity` | 月 | 60 天 | — | P1 |
| 宏观 | 吉林电网代购价 | cn | `cn_macro_power_px_jl_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 名酒一批价 | cn | `cn_macro_baijiu_batch` | 日 | 5 天 | — | P1 |
| 宏观 | 四川电网代购价 | cn | `cn_macro_power_px_sc_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 天津电网代购价 | cn | `cn_macro_power_px_tj_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 宁夏电网代购价 | cn | `cn_macro_power_px_nx_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 安徽电网代购价 | cn | `cn_macro_power_px_ah_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 山东电网代购价 | cn | `cn_macro_power_px_sd_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 山西电网代购价 | cn | `cn_macro_power_px_sx_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 巴西海关镜像 | cn | `cn_macro_br_comexstat` | 月 | 60 天 | — | P1 |
| 宏观 | 广东中长期综合价 | cn | `cn_macro_power_px_gd_midlong` | 月 | 60 天 | — | P1 |
| 宏观 | 广东月竞综合价 | cn | `cn_macro_power_px_gd_bid` | 月 | 60 天 | — | P1 |
| 宏观 | 广东电网代购价 | cn | `cn_macro_power_px_gd_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 广西电网代购价 | cn | `cn_macro_power_px_gx_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 德国包裹市场年度件量收入 | cn | `cn_macro_postal_de` | annual | 800 天 | — | P1 |
| 宏观 | 快递业务量 | cn | `cn_macro_spb_express` | 月 | 60 天 | — | P1 |
| 宏观 | 房地产市场 | cn | `cn_macro_nbs_real_estate` | 月 | 60 天 | — | P1 |
| 宏观 | 新疆电网代购价 | cn | `cn_macro_power_px_xj_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 新能源汽车产销 | cn | `cn_macro_cpca_nev` | 月 | 60 天 | — | P1 |
| 宏观 | 日本宅配便年度実績 | cn | `cn_macro_postal_jp_annual` | annual | 900 天 | — | P1 |
| 宏观 | 日本宅配便月度取扱個数 | cn | `cn_macro_postal_jp` | 月 | 120 天 | — | P1 |
| 宏观 | 欧盟海关HS | cn | `cn_macro_eu_comext_hs` | 月 | 50 天 | — | P1 |
| 宏观 | 江苏电网代购价 | cn | `cn_macro_power_px_js_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 江西电网代购价 | cn | `cn_macro_power_px_jx_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 河北电网代购价 | cn | `cn_macro_power_px_he_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 河南电网代购价 | cn | `cn_macro_power_px_ha_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 法国包裹市场 | cn | `cn_macro_postal_fr` | annual | 800 天 | — | P1 |
| 宏观 | 浙江电网代购价 | cn | `cn_macro_power_px_zj_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 海关HS | cn | `cn_macro_comtrade_hs` | 月 | 400 天 | — | P1 |
| 宏观 | 海关月报量值 | cn | `cn_macro_gacc_monthly` | 月 | 60 天 | — | P1 |
| 宏观 | 海南电网代购价 | cn | `cn_macro_power_px_hn_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 甘肃电网代购价 | cn | `cn_macro_power_px_gs_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 社零 | cn | `cn_macro_nbs_retail` | 月 | 60 天 | — | P1 |
| 宏观 | 福建电网代购价 | cn | `cn_macro_power_px_fj_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 系别结构 | cn | `cn_macro_cpca_origin` | 月 | 60 天 | — | P1 |
| 宏观 | 级别结构 | cn | `cn_macro_cpca_segment` | 月 | 60 天 | — | P1 |
| 宏观 | 统计局精选全量 | cn | `cn_macro_nbs_std` | 月 | 60 天 | — | P1 |
| 宏观 | 美国USPS季度邮件量 | cn | `cn_macro_postal_us` | quarterly | 200 天 | — | P1 |
| 宏观 | 美国海关镜像 | cn | `cn_macro_us_census` | 月 | 60 天 | — | P1 |
| 宏观 | 航交所运价SCFI | cn | `cn_macro_sse_freight_index` | weekly | 10 天 | — | P1 |
| 宏观 | 英国邮政监测 | cn | `cn_macro_postal_uk` | annual | 700 天 | — | P1 |
| 宏观 | 贵州电网代购价 | cn | `cn_macro_power_px_gz_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 车型大类 | cn | `cn_macro_cpca_body` | 月 | 60 天 | — | P1 |
| 宏观 | 辽宁电网代购价 | cn | `cn_macro_power_px_ln_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 运价指数BDI | cn | `cn_macro_shipping_index` | 日 | 5 天 | — | P1 |
| 宏观 | 重庆电网代购价 | cn | `cn_macro_power_px_cq_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 陕西电网代购价 | cn | `cn_macro_power_px_snx_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 青海电网代购价 | cn | `cn_macro_power_px_qh_agency` | 月 | 60 天 | — | P1 |
| 宏观 | 韩国택배月度件量 | cn | `cn_macro_postal_kr` | 月 | 90 天 | — | P1 |
| 宏观 | 黑龙江电网代购价 | cn | `cn_macro_power_px_hl_agency` | 月 | 60 天 | — | P1 |
| 机构持仓 | 机构持仓占比 | cn | `cn_stock_gdyj_jgcczb` | 季（A 股） | 90 天 | — | P1 |
| 机构持仓 | 机构明细 | cn | `cn_stock_gdyj_jgmx` | 季（A 股） | 90 天 | — | P1 |
| 机构持仓 | 机构统计 | cn | `cn_stock_gdyj_jgtj` | 季（A 股） | 90 天 | — | P1 |
| 盈利预测 | 机构预测 | cn | `cn_stock_ylyc_jgyc` | 季（A 股） | 90 天 | — | P1 |
| 盈利预测 | 评级统计 | cn | `cn_stock_ylyc_pjtj` | 季（A 股） | 90 天 | — | P1 |
| 股本变动 | 股本变动 | cn | `cn_stock_equity_change` | 时间戳 | 90 天 | — | P1 |
| 资本运作 | 资金募集进度 | cn | `cn_stock_zbyz_zjmjjd` | 时间戳 | 90 天 | — | P1 |
| 利率 | LPR利率 | cn | `cn_lpr_rate` | 月 | 35 天 | — | P2 |
| 回购 | 回购明细 | cn | `cn_gphg_hgmx` | 时间戳 | 10 天 | — | P2 |
| 宏观 | 公募AUM | cn | `cn_macro_amac_fund_nav` | 月 | 70 天 | — | P2 |
| 宏观 | 原保险保费 | cn | `cn_macro_nfra_insurance` | 月 | 60 天 | — | P2 |
| 宏观 | 啤酒产量 | cn | `cn_macro_nbs_beer` | 月 | 120 天 | — | P2 |
| 宏观 | 生鲜乳周价 | cn | `cn_macro_moa_raw_milk` | weekly | 14 天 | — | P2 |
| 宏观 | 白酒产量 | cn | `cn_macro_nbs_baijiu` | 月 | 120 天 | — | P2 |
| 宏观 | 社融存量 | cn | `cn_macro_tsf_stock` | 月 | 60 天 | — | P2 |
| 宏观 | 股基成交额 | cn | `cn_macro_stockfund_turnover` | 月 | 45 天 | — | P2 |
| 宏观 | 食饮产量 | cn | `cn_macro_nbs_food` | 月 | 60 天 | — | P2 |
| 并购重组 | 并购重组 | cn | `cn_stock_bgcz` | 时间戳 | 10 天 | — | P2 |
| 沪港通 | 沪港通持股 | cn | `cn_stock_gdyj_hgtcg` | 日 | 10 天 | — | P2 |
| 股东 | 十大股东 | cn | `cn_stock_free_holders` | 季（A 股） | 90 天 | — | P2 |
| 股东 | 股东人数 | cn | `cn_stock_holder_num` | 季（A 股） | 90 天 | — | P2 |
| 质押 | 质押概况 | cn | `cn_gqzy_sctj` | 事件驱动 | 10 天 | — | P2 |

## 口径说明

1. **过期阈值**按数据类型的自然更新节奏设（日更类 3~7 天、季报类 100~120 天），不是统一 SLA；以本表为准。
2. **预警阈值**用于「漏一期」在 T+1 被看见（早于过期阈值先黄），None = 未启用提前预警。
3. 两融/日历等 2.0 新增面在 airflow 独立 DAG + `verify.freshness_hours` 中另有约束（48h 默认），见对应 DAG 定义。
