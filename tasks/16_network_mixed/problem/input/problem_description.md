# Supply chain network optimization under central warehouse hybrid storage - Technical requirements document

---

## 1. Problem background

The company's finished product supply chain has four levels of sites from top to bottom: raw material suppliers, factories, central warehouses, regional distribution centers, and the most downstream are customers. The factory consumes raw materials according to the formula to produce finished products. The finished products enter the central warehouse and are then distributed to regional distribution centers and finally delivered to customers. Finished products are divided into two categories, and the two categories have different capital occupation intensity, transportation temperature control requirements and freight rates.

This round allows two central warehouses in Jiaxing (C01) and Guangzhou (C02) to store and distribute chocolate and candies at the same time. Each factory can send the finished products it is allowed to produce to any central warehouse, and both central warehouses can distribute two types of finished products to all regional distribution centers.

The company also proposed a new service distance goal: the demand met by terminal supply nodes that are close enough to customers must account for a lower proportion of the total annual demand. The existing network is far from achieving this goal, so capacity allocation, finished product flows and customer supply relationships need to be rearranged. This question does not require submission of inventory strategies; inventory holding costs are uniformly derived from network traffic, fixed shipping intervals and transportation time.

Whether a site is activated or not is not free: as long as a site carries traffic, it will be activated and billed, and if it does not bear traffic, it will not be billed. Factory capacity, feasible lanes, and service distance minimums all combine to determine which sites cannot actually be closed.

---

## 2. Optimization goals

In this question, after all hard constraints are met, the total annual supply chain cost is directly compared. The lower the cost, the better. The coverage of the number of pieces required within 480km is only used for the hard constraints in Section 4.5 and does not enter the scoring. The 95% inventory service level is not part of this question and does not contribute to feasibility or scoring.

Section 4.3 requires that all customer demand is produced and delivered, so the order revenue for any feasible solution is the same constant; the cost dimension directly uses the total annual supply chain cost.

```text
Order revenue = number of items satisfied throughout the year x sales price (constant of feasible solutions)
Total supply chain cost = node operating cost + production cost + transportation cost + inventory holding cost
Total order profit = order revenue - total supply chain cost
```

The caliber of the four costs is as follows.

**Node operating costs**. When the total annual output of a factory is greater than 0, the fixed_operating_cost of the factory will be fully included in the annual node operating cost, and will not be converted in proportion to the output; when the annual output is 0, the fixed operating cost of the factory will not be included. The central warehouse and regional distribution center are billed according to the annual throughput in different brackets: the bracket table gives several "throughput thresholds -> annual fees", and the actual cost is the highest bracket with the threshold not exceeding the annual throughput of the node; the highest bracket has no upper bound, and the throughput exceeding the highest threshold is still billed according to the highest bracket. **The gear table is a cost breakpoint, not a throughput upper limit. **

The annual throughput of the warehouse is calculated based on the number of finished products shipped throughout the year, summarizing all finished products. CDC throughput is the number of pieces shipped to RDC; RDC throughput is the number of pieces shipped to customers throughout the year. Incoming and outgoing items are not added repeatedly. For example, if 100,000 items are received and 100,000 items are sent out, the throughput is 100,000 items. A central warehouse or regional distribution center with a throughput of zero is considered inactive and will not be billed.

**Production Cost**. The production cost is accumulated based on the actual production number of each finished product multiplied by the unit production cost of the finished product; the unit production cost uses `production_cost` in the product data and does not change due to different production plants.

**Shipping Cost**. Calculate segment by lane and sum. Raw material sections are charged by weight, and each section of finished product is charged by volume:

```text
The freight is calculated based on the shipping quantity, the billing basis given by the lane, the distance and the freight rate; raw materials and finished products use the billing basis specified by their respective data.
```

Freight rate, distance, transportation time, and shipping interval are determined by lane data and mixing rules in Section 4.2, and are not selected by the plan.

The unit of `unit_weight` is kilogram/piece, the unit of `unit_volume` is cubic meter/piece, and the unit of `distance_km` is kilometers. In this question, `cmtr` (originally written as `CMTR`) represents cubic meters (m³): `yuan_per_cmtr_km` represents yuan/(cubic meter·km), and `yuan_per_kg_km` represents yuan/(kilogram·km). The raw material section uses the `unit_weight` of the raw material, and each section of the finished product (including terminal distribution) uses the `unit_volume` of the finished product, which is billed in conjunction with the `freight_rate` of the corresponding lane; the input weight and volume have been in the above units, and there is no need to make additional unit conversions.

**Inventory Carrying Cost**. Calculate circulating inventory and in-transit inventory from flow rates as per Section 5.

The `Fixed Procurement Cost` field does not enter into the total supply chain cost.

---

## 3. Decision-making and submission standards

The plan needs to give four parts of decisions at the same time:

1. **Output**: The annual output of each finished product in each factory.
2. **Finished product flow from factory to central warehouse**: Each factory sends each finished product to which central warehouse and how many pieces are sent.
3. **Finished product flow from central warehouse to regional distribution center**: Each central warehouse sends each finished product to which regional distribution center and how many pieces are sent.
4. **Customer supply relationship**: Which end supply nodes are supplied by each "customer x specific product" combination, and the number of pieces delivered at each node.

The number of pieces is always a non-negative integer. Transportation modes, inventory strategies, and committed service times are not decisions; each lane's temperature control mode, freight rate, distance, transportation time, and shipping interval are determined by data and the rules of Section 4.2. The system uniformly recalculates costs and coverage, and does not accept self-reported indicators.

---

## 4. Hard constraints (must be met)

### 4.1 Output structure

The submission must be a JSON object and contain only four arrays: `production`, `factory_to_cdc`, `cdc_to_rdc`, and `customer_service`. The required fields for each array record are as follows:

- `production`：`factory`、`product`、`pieces`。
- `factory_to_cdc`：`factory`、`cdc`、`product`、`pieces`。
- `cdc_to_rdc`：`cdc`、`rdc`、`product`、`pieces`。
- `customer_service`：`customer`、`product`、`node`、`pieces`。

Fill in the site, customer and finished product fields with the number string in the instance; `product` represents the specific finished product and cannot be replaced by its category. `pieces` is a non-negative integer number of pieces, and this field cannot be replaced by `qty` or `quantity`; the terminal supply node uses `node` uniformly, and cannot be replaced by `serving_node`.

Compatible with the entire history of `customer_service` submitted using `customer, category, node`: the system expands customer product traffic according to instance requirements, and each customer category in need must still have exactly one. The old format cannot express splits and cannot be mixed with the new format.

### 4.2 Network path

Raw materials can only flow from suppliers to factories. Finished products must be circulated according to "Factory → Central Warehouse → Regional Distribution Center → Customer", and customers are not allowed to be supplied directly from the central warehouse; however, which central warehouse the finished product enters is no longer fixed by category.

The original legal transportation routes that comply with the network level of this question will continue to be available, and the transportation parameters of the two mixed routes will be implemented in accordance with the regulations of this round. When the transportation record is not listed, the scope of the allowed supplement is limited to the two paragraphs "Factory→Central Warehouse" and "Central Warehouse→Regional Distribution Center", and only the sites already in the data can be used, without changing the factory's list of producible products and production capacity limits.

Finished products must still go through "factory → central warehouse → regional distribution center → customer". The factory is not open to directly supply regional distribution centers or customers, nor is the central warehouse open to directly supply customers, transfer goods between central warehouses, transfer goods between regional distribution centers, or reverse transportation. The transportation relationship between supplier → factory, regional distribution center → customer is still based on the original data and cannot be added based on this round of mixed storage permission.

Within the two paragraphs that are allowed to be added, the existing distance and transportation time between the source and destination in the same direction can be reused across categories; if a category is not listed separately, it does not mean that transportation is prohibited for that category. The transportation mode is determined according to the following provisions of this round, and another category will not be excluded because historical records only indicate constant temperature or normal temperature. Existing distance and transportation time cannot be shortened on their own, and zero distance is not considered missing.

If there is indeed a lack of distance between these two sections, the spherical great circle distance can be calculated based on the site's longitude and latitude. The spherical radius is 6371 kilometers, multiplied by 1.17, and rounded to 4 decimal places. If there is indeed a shortage of transportation days, the distance shall be divided by 1320 and then rounded up, with the lowest being 1 day. Existing values ​​will be used first; if necessary coordinates are missing, please check with us and do not guess on your own. This supplementary calculation method is not applicable to other transportation segments, especially cannot be used to change the service distance from the regional distribution center to the customer.

When the factory transports candies to any central warehouse, it adopts normal-temperature transportation at a rate of 0.24 yuan/(cubic meter·km) and is shipped every three days; when transporting chocolate, it uniformly uses constant-temperature transportation at a rate of 0.47 yuan/(cubic meter·km) and is shipped every three days. These regulations also apply to the two central warehouses in Jiaxing and Guangzhou.

Candies transported from any central warehouse to the regional distribution center are transported at room temperature at a rate of 0.39 yuan/(cubic meter·km), and are shipped every 2 days.

When transporting chocolate from any central warehouse to regional distribution centers in Shanghai (R01), Guangzhou (R02), Chengdu (R03), and Wuhan (R05), constant temperature transportation is used, and the rate is 1.02 yuan/(cubic meter·km), every 3 It is shipped once every day; if it is shipped to regional distribution centers in Kunming (R04), Shenyang (R06), Xi'an (R07), and Zhengzhou (R08), it will be transported at room temperature with a rate of 0.45 yuan/(cubic meter·km) and shipped every 2 days.

The above parameters are implemented based on category and transportation segment, and you cannot choose other rates or shipping intervals; the shipping interval is not equal to the number of days of transportation.

The annual inventory holding ratio of finished goods in both central warehouses is determined by category: 15% for confectionery and 16% for chocolate. The supplementary route is included in the cost of transportation, circulating inventory and in-transit inventory in the same way as the original route, and the specific billing method follows the original regulations. The warehouse operating fee is based on the total throughput of the two types of finished products. The operating fee for the entire warehouse will not be charged repeatedly because the two types of products are stored at the same time.

### 4.3 Full demand satisfaction and material balance

All customer needs must be produced and delivered, and the sending and receiving of each layer of sites are equal:

```text
Total output of each finished product = total annual demand for the finished product
The total output of each factory <= the upper limit of the factory’s production capacity
The factory’s output of each finished product = the factory’s output of that finished product
Revenue of each finished product in the central warehouse = Output of the finished product in the central warehouse (including transshipment)
Regional distribution center revenue = total number of pieces of finished product delivered to customers
```

The upper limit of production capacity is the upper limit of the sum of the output of all finished products in the entire factory, not the upper limit of a single finished product.

`capacity_pieces` is the upper limit of the total output of all finished products of the factory throughout the year, in units of pieces/year; different finished products of the same factory jointly occupy this production capacity quota, not each finished product has an equal quota.

### 4.4 Customer supply relationship

The only candidate terminal supply nodes are regional distribution centers. The same customer's demand for the same specific product can be split among multiple regional distribution centers, with each center supplying goods based on the number of pieces submitted.

The total number of delivered pieces for each "customer x specific product" combination at all supply nodes must be exactly equal to the customer's demand for the product, and no short supply or over supply is allowed. Do not deliver positive quantities to customer product portfolios for which there is no demand. Multiple records of the same customer, product and node are accumulated based on the number of pieces; zero quantity records do not form a supply.

### 4.5 Lower limit of service distance coverage

The proportion of the number of demand pieces borne by the end supply node that is no more than `service_distance_km` from the customer to the total number of demand pieces throughout the year shall not be less than `service_coverage_floor`.

All customer demand must be produced and delivered, of which at least 75% of the annual demand units must be supplied by end nodes no more than 480km away from the customer. The remaining demand must also be fully delivered and can be supplied by more distant feasible nodes; 75% is a close service coverage requirement, not a requirement that only 75% of the demand is allowed to be delivered.

```text
Service distance coverage = number of demand pieces met within the service distance / total number of demand pieces >= service_coverage_floor
```

This ratio is calculated based on the number of pieces required by all customers and all finished products, and is not calculated separately by the number of orders, number of customers, order amount, weight or individual customers. The distance is judged based on the distance from the end supply node to the customer in the lane data.

The instance's `totals.max_service_coverage` gives a **theoretical bound** on this ratio for this network, that is, the ratio that can be achieved if each customer is served by the nearest feasible node to it. This upper bound is not far from the lower bound, and the coverage constraint is usually tight in this problem.

---

## 5. Inventory and holding cost caliber

This question does not determine safety stock, nor does it have a 95% inventory service level. Inventory holding costs include only circulating inventory and in-transit inventory that are directly derived from network traffic:

```text
Inventory holding costs are determined by annual flow, fixed shipping intervals, transportation time, unit value and annual holding cost rate; see the inventory range description for specific inclusion ranges.
```

Circular inventory is also called turnover inventory. The average circulating inventory is calculated according to `F × RF / (2 × T)` for each lane included in the cycle inventory: F is the annual flow rate of the raw material or finished product in the lane, RF is the two replenishment intervals (days) given by the lane field `shipment_interval_days`, T is `days_per_year`, and this question is 365. RF represents the number of days between intervals, not the number of replenishments per year; the annual flow rate must first be converted into average daily flow rate. The calculation is the average inventory quantity, not the cost.

Annual cycle inventory holding cost = average cycle inventory quantity × `unit_value` of the material or finished product × annual holding cost rate. When the supplier goes to the factory to calculate the factory's raw material circulating inventory, use the factory's `holding_rate_material'; when the factory goes to the CDC to calculate the CDC's finished product circulating inventory, use the `holding_rate' of the CDC's corresponding category; when the CDC goes to the RDC to calculate the RDC's finished product circulating inventory, use the RDC's corresponding category's holding_rate'. The circulating inventory from the end node to the customer is not included.

The average quantity of inventory in transit for each transport lane is calculated as `F × LT / T`: F is the annual flow of the lane, LT is the number of transit days given by the lane field `transit_days`, T is `days_per_year`, which is 365 in this question. `transit_days` is determined by input data or the computation rules of Section 4.2, not a program decision, and does not include `shipment_interval_days`. The annual holding cost rate of inventory in transit is determined by transportation segment: from the supplier to the factory, use the `holding_rate_material` of the receiving factory; from the factory to the CDC, use the `holding_rate` of the receiving CDC corresponding to the finished product category; from CDC to RDC, use the `holding_rate` of the receiving RDC corresponding to the finished product category; from the end node to the customer, use the `holding_rate` of the shipping node corresponding to the finished product category. The raw material in-transit inventory uses the `unit_value` of the raw material, and the finished product in-transit inventory uses the `unit_value` of the finished product.

`Unit value` is the base price for calculating carrying costs and is neither the purchase price nor the sales price. `Inventory holding cost rate` is given by site and category, and there is another level for raw materials.

Circulating inventory is counted at the receiving inventory point of each inbound lane; in-transit inventory covers the transportation segments from supplier to factory, factory to CDC, CDC to RDC, and end node to customer; factory finished goods, CDC, and RDC safety stocks are not counted.

---

## 6. Input data format

| Field | Description |
|:---|:---|
| `case_id`, `contract_version`, `variant` | Instance number, contract version and network path rule identification of this question |
| `planning_year`, `days_per_year` | Planning year and number of days throughout the year |
| `service_distance_km`, `service_coverage_floor` | Service distance and coverage lower limit |
| `products` | Finished products, including `category`, `sale_price`, `unit_value`, `unit_weight`, `unit_volume`, `production_cost` |
| `materials` | Raw materials, including `unit_value`, `unit_weight`, `supplier` |
| `bom` | `bom[finished product][raw material]` is the number of raw materials consumed for each finished product |
| `factories` | Factories, including `category`, `products` (list of finished products that can be produced), `fixed_operating_cost`, `capacity_pieces`, `holding_rate_finished`, `holding_rate_material` |
| `central_warehouses`, `regional_centers` | Contains `operating_cost_tiers` (`[throughput threshold, annual cost]` list) and `holding_rate` by category |
| `customers` | Customers, including `temperature_zone` and `demand` (annual demand) |
| `arcs` | Four segments of lane data, see below |
| `mixed_transport_records` | The two sections in the original data can supplement the same-way distance and transportation days of the line for cross-category reuse |
| `totals` | Summary check values: `demand_pieces`, `revenue_at_full_service`, `production_cost_at_full_service`, `max_service_coverage` |

`arcs` is divided into four sections, and the key structure is as follows:

| lane segment | key | field |
|:---|:---|:---|
| `supplier_to_factory` | `supplier\|factory\|raw material` | `mode`, `distance_km`, `transit_days`, `freight_rate`, `freight_basis`, `shipment_interval_days`, `procurement_lead_days`, `fixed_purchase_cost` |
| `factory_to_cdc` | `Factory\|Central Warehouse` | Same as above (without `fixed_purchase_cost`), and give the `category` carried by the lane |
| `cdc_to_rdc` | `Central warehouse\|Regional distribution center\|Category` | Same as above |

Factory → Central Warehouse, Central Warehouse → Regional Distribution Center supplements and unifies transportation parameters according to Section 4.2; relationships not provided in other transportation segments are still unavailable. `freight_basis` explains the billing basis: the raw material section is based on `yuan_per_kg_km`, and the finished product section is based on `yuan_per_cmtr_km`.

`node_to_customer` gives the terminal delivery data: `distance_km[node][customer]` is the distance, `transit_days[node][customer]` is the number of transportation days, **The key set is the candidate terminal supply node set for this question**; the freight rate is checked according to category and temperature control mode `freight_rate`; see the mode rules `mode_rule` - Candy is fixed at normal temperature in all end lanes, chocolate is at constant temperature for customers whose temperature control zone is constant temperature, and the rest is at normal temperature.

Factories, central warehouses and regional distribution centers also provide `city`, `latitude` and `longitude` (latitude and longitude are angles). In this example, two mixed storage routes have been completed; if there are missing records, please follow Section 4.2.

The specific values ​​of each official case are only provided when the solver reads `input_file`.

---

## 7. This scenario is not included in the judgment.

The following matters do not constitute constraints in the judgment and scoring of this scenario, and the supporting data are not sufficient for verification:

- **Node Storage Capacity**: The data only provides the throughput cost bracket, but does not provide an upper limit for inventory. There is no upper limit for inventory. The throughput level is a cost breakpoint and cannot be used as a capacity constraint.
- **Fixed procurement cost**: The data gives the fixed procurement cost according to the procurement relationship, but does not give the procurement batch caliber and cannot be converted to the year, so it is not included in the total cost.
- **Transportation mode selection**: The temperature control mode of each lane is uniquely determined by the original data and the mixing rules in Section 4.2, and is not a decision.

---

## 8. Delivery requirements

- All four arrays must be given, `pieces` is an integer.
- `customer_service` covers all required "customer x specific product" combinations and can be supplied in multiple records. The total number of pieces must be equal to the demand.
- Do not submit cost, profit, coverage, or score fields; these metrics are recalculated by the system.
