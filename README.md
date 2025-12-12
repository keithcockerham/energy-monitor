# Energy Disaggregation ML Portfolio Project
# Just started!  Stay tuned for improvements
## Progress at: https://keithcockerham.github.io/energy-monitor/
## Non-Intrusive Load Monitoring (NILM) System

---

## Executive Summary

This project demonstrates end-to-end machine learning on real-time energy data from a residential electrical panel. The system captures split-phase electrical measurements at 1-second intervals, enabling device recognition, anomaly detection, and energy attribution without sub-metering individual circuits.

**Your Data Profile:**
- **Sampling Rate:** 1 Hz (1-second intervals)
- **Electrical System:** Split-phase 120V (US residential standard)
- **Measurements per phase:** Voltage, Current, Active Power, Apparent Power, Power Factor, Frequency
- **Derived Metrics:** Reactive power, total consumption, phase imbalance

---

## Planned Project Architecture

### Shelly Pro 3EM 120V --BT--> Raspberry Pi Zero 2W for capture
### RPi --WiFi--> PC for batched retrieval 
---

## Phase 1: Data Infrastructure & Visualization

### 1.1 Data Storage Strategy

### 1.2 Feature Engineering

**Raw Features (from your data):**
| Feature | Description | Used For |
|---------|-------------|----------|
| `a_act_power`, `b_act_power` | Real power per phase | Primary consumption metric |
| `a_aprt_power`, `b_aprt_power` | Apparent power | Motor/reactive load detection |
| `a_pf`, `b_pf` | Power factor | Device type fingerprinting |
| `a_current`, `b_current` | Current draw | Inrush current detection |
| `a_voltage`, `b_voltage` | Voltage level | Normalize measurements |

### 1.3 Interactive Visualization Dashboard

**Recommended Stack:** Plotly Dash or Streamlit

```
Dashboard Layout:

[Date Range Selector]  [Phase Filter]  [Resolution: 1s/1m/1h] 
[REAL-TIME POWER CONSUMPTION]
[Interactive line chart with event markers]

[EVENT LOG]  
[Table with detected events]
[Interactive line chart with event markers]

```
---

## Phase 2: Event Detection (Unsupervised)

### 2.1 Change Point Detection Algorithms

**Method 1: CUSUM (Cumulative Sum)**

**Method 2: Bayesian Online Changepoint Detection**

**Method 3: Simple Derivative Threshold (Baseline)**

### 2.2 Event Characterization Features

For each detected event, extract a "signature":

---

## Phase 3: Device Recognition (Supervised Learning)

### 3.1 Training Data Collection Strategy

**Manual Labeling Interface:**

**Labeling Strategy:**
1. Start with high-power, distinctive devices (HVAC, EV Charger, oven)
2. Label 20-50 events per device class for initial training
3. Use active learning to prioritize uncertain predictions

### 3.2 Model Architectures

**Model 1: XGBoost on Engineered Features (Baseline)**

**Model 2: 1D CNN on Power Trajectories**

**Model 3: LSTM for Temporal Patterns**

### 3.3 Handling Class Imbalance

Some devices trigger rarely (water heater) vs constantly (refrigerator):

#### Option 1: SMOTE oversampling

#### Option 2: Class weights

#### Option 3: Focal loss (for neural networks)

---

## Phase 4: New Device Detection (Novelty Detection)

Detect when an unknown device appears in your home.

### 4.1 Approach: One-Class Classification

### 4.2 Clustering Unknown Events

---

## Phase 5: Anomaly Detection for Device Health

Check for device distress

### 5.1 Per-Device Baseline Modeling

### 5.2 Device-Specific Health Indicators

## Tech Stack Recommendations
