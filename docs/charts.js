// Energy Dashboard Charts
// Loads data from Azure Functions API

let dashboardData = null;
const API_BASE = 'https://nilm-functions-e7c9bnc9e3hxbac7.centralus-01.azurewebsites.net/api';

// Chart color scheme matching portfolio style
const colors = {
    primary: '#667eea',
    secondary: '#764ba2',
    accent: '#11998e',
    success: '#38ef7d',
    warning: '#f5576c',
    phaseA: '#667eea',
    phaseB: '#38ef7d',
    background: '#f7fafc',
    gridline: '#e2e8f0'
};

// Standard layout options
const baseLayout = {
    plot_bgcolor: colors.background,
    paper_bgcolor: '#ffffff',
    font: { family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' },
    margin: { t: 40, b: 50, l: 60, r: 40 }
};

const config = { responsive: true, displayModeBar: false };

// Update metrics cards
function updateMetrics(data) {
    document.getElementById('metric-samples').textContent = data.sampleCount?.toLocaleString() || '--';
    document.getElementById('metric-events').textContent = data.eventCount || '--';
    document.getElementById('metric-power').textContent = data.avgPower?.toFixed(0) || '--';
}

// Timezone for display
const TIMEZONE = 'America/Chicago';

// Convert UTC timestamps to local time in ISO format (Plotly-parseable)
function toLocalTime(utcTimestamps) {
    return utcTimestamps.map(ts => {
        const date = new Date(ts + 'Z');  // Parse as UTC
        // Use sv-SE locale for ISO-like format: YYYY-MM-DD HH:MM:SS
        return date.toLocaleString('sv-SE', { timeZone: TIMEZONE });
    });
}

// Power Consumption Chart
function createPowerChart(timeseries) {
    const localTimes = toLocalTime(timeseries.timestamps);
    
    const powerTrace = {
        x: localTimes,
        y: timeseries.total_power,
        type: 'scatter',
        mode: 'lines',
        name: 'Total Power',
        line: { color: colors.primary, width: 1.5 },
        fill: 'tozeroy',
        fillcolor: 'rgba(102, 126, 234, 0.1)'
    };

    const layout = {
        ...baseLayout,
        height: 500,
        xaxis: { 
            title: 'Time (Central)',
            type: 'date',
            rangeslider: { visible: true },
            rangeselector: {
                buttons: [
                    { count: 5, label: '5m', step: 'minute', stepmode: 'backward' },
                    { count: 30, label: '30m', step: 'minute', stepmode: 'backward' },
                    { count: 1, label: '1h', step: 'hour', stepmode: 'backward' },
                    { count: 6, label: '6h', step: 'hour', stepmode: 'backward' },
                    { step: 'all', label: 'All' }
                ]
            }
        },
        yaxis: { title: 'Power (W)', rangemode: 'tozero' },
        legend: { orientation: 'h', y: 1.15 },
        hovermode: 'x unified'
    };

    Plotly.newPlot('powerChart', [powerTrace], layout, config);
}

// Phase Comparison Chart
function createPhaseChart(metrics) {
    const trace1 = {
        x: ['Phase A', 'Phase B'],
        y: [metrics.avgPowerA, metrics.avgPowerB],
        type: 'bar',
        marker: { 
            color: [colors.phaseA, colors.phaseB],
            line: { color: [colors.primary, colors.accent], width: 2 }
        },
        text: [`${metrics.avgPowerA.toFixed(1)} W`, `${metrics.avgPowerB.toFixed(1)} W`],
        textposition: 'outside'
    };

    const layout = {
        ...baseLayout,
        title: { text: 'Average Power by Phase', font: { size: 16 } },
        height: 350,
        yaxis: { title: 'Power (W)', range: [0, Math.max(metrics.avgPowerA, metrics.avgPowerB) * 1.3] },
        showlegend: false
    };

    Plotly.newPlot('phaseChart', [trace1], layout, config);
}

// Power Factor Chart
function createPowerFactorChart(metrics) {
    const trace = {
        type: 'indicator',
        mode: 'gauge+number+delta',
        value: metrics.avgPF,
        title: { text: 'Combined Power Factor', font: { size: 16 } },
        delta: { reference: 0.95, increasing: { color: colors.success } },
        gauge: {
            axis: { range: [0, 1], tickformat: '.2f' },
            bar: { color: colors.primary },
            bgcolor: 'white',
            borderwidth: 2,
            bordercolor: colors.gridline,
            steps: [
                { range: [0, 0.7], color: colors.warning + '40' },
                { range: [0.7, 0.9], color: colors.accent + '40' },
                { range: [0.9, 1], color: colors.success + '40' }
            ],
            threshold: {
                line: { color: colors.warning, width: 4 },
                thickness: 0.75,
                value: 0.8
            }
        }
    };

    const layout = {
        ...baseLayout,
        height: 350
    };

    Plotly.newPlot('powerFactorChart', [trace], layout, config);
}

// Event Detection Chart (Power Change)
function createEventChart(events) {
    if (!events || events.length === 0) {
        document.getElementById('eventChart').innerHTML = 
            '<p style="text-align:center;padding:2rem;color:#718096;">No events detected yet</p>';
        return;
    }
    
    const localTimes = toLocalTime(events.map(e => e.time));
    const deltas = events.map(e => e.delta);
    const barColors = events.map(e => e.type === 'ON' ? colors.success : colors.warning);
    
    const trace = {
        x: localTimes,
        y: deltas,
        type: 'bar',
        marker: { color: barColors },
        text: events.map(e => `${e.type}: ${e.delta > 0 ? '+' : ''}${e.delta.toFixed(0)}W`),
        textposition: 'outside',
        hovertemplate: '<b>%{x}</b><br>ΔPower: %{y:.1f}W<extra></extra>'
    };

    const layout = {
        ...baseLayout,
        height: 400,
        title: { text: 'Detected Power Events (ΔP > 200W)', font: { size: 16 } },
        xaxis: { 
            title: 'Time (Central)', 
            type: 'date',
            rangeslider: { visible: true }
        },
        yaxis: { 
            title: 'Power Change (W)', 
            zeroline: true, 
            zerolinecolor: colors.gridline, 
            zerolinewidth: 2,
            autorange: true
        },
        showlegend: false
    };

    Plotly.newPlot('eventChart', [trace], layout, config);
    
    // Rescale y-axis when x-axis range changes
    const chartEl = document.getElementById('eventChart');
    chartEl.on('plotly_relayout', function(eventData) {
        if (eventData['xaxis.range[0]'] || eventData['xaxis.range']) {
            const xRange = eventData['xaxis.range'] || 
                [eventData['xaxis.range[0]'], eventData['xaxis.range[1]']];
            
            // Find visible events
            const visibleDeltas = [];
            for (let i = 0; i < localTimes.length; i++) {
                const t = new Date(localTimes[i]).getTime();
                const t0 = new Date(xRange[0]).getTime();
                const t1 = new Date(xRange[1]).getTime();
                if (t >= t0 && t <= t1) {
                    visibleDeltas.push(deltas[i]);
                }
            }
            
            if (visibleDeltas.length > 0) {
                const minY = Math.min(...visibleDeltas);
                const maxY = Math.max(...visibleDeltas);
                const padding = (maxY - minY) * 0.15 || 50;
                
                Plotly.relayout('eventChart', {
                    'yaxis.range': [minY - padding, maxY + padding]
                });
            }
        }
    });
}

// Populate Events Table
function populateEventsTable(events) {
    const tbody = document.querySelector('#eventsTable tbody');
    if (!tbody) return;
    
    tbody.innerHTML = '';

    if (!events || events.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#718096;">No events detected yet</td></tr>';
        return;
    }

    events.slice(0, 20).forEach(event => {  // Show top 20 events
        const row = document.createElement('tr');
        const statusBadge = event.labeled ? 
            '<span class="badge-success">Labeled</span>' : 
            '<span class="badge-warning">Unlabeled</span>';
        
        // Convert to local time
        const localTime = new Date(event.time + 'Z').toLocaleString('en-US', { 
            timeZone: TIMEZONE,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
        
        row.innerHTML = `
            <td>${localTime}</td>
            <td><strong style="color: ${event.type === 'ON' ? colors.success : colors.warning}">${event.type}</strong></td>
            <td>${event.delta > 0 ? '+' : ''}${event.delta.toFixed(1)}</td>
            <td>Phase ${event.phase}</td>
            <td>${event.device}</td>
            <td>${statusBadge}</td>
        `;
        tbody.appendChild(row);
    });
}

// Show loading state
function showLoading() {
    document.querySelectorAll('.chart-container').forEach(el => {
        el.innerHTML = '<p style="text-align:center;padding:2rem;color:#718096;">Loading data from Azure...</p>';
    });
}

// Show error state
function showError(message) {
    document.querySelectorAll('.chart-container').forEach(el => {
        el.innerHTML = `<p style="text-align:center;padding:2rem;color:#f5576c;">${message}</p>`;
    });
}

// Initialize all charts on page load
document.addEventListener('DOMContentLoaded', async function() {
    showLoading();
    
    try {
        // Fetch data from Azure API
        const response = await fetch(`${API_BASE}/dashboard?hours=6&downsample=5`);
        
        if (!response.ok) {
            throw new Error(`API returned ${response.status}: ${response.statusText}`);
        }
        
        dashboardData = await response.json();
        
        if (dashboardData.error) {
            throw new Error(dashboardData.error);
        }
        
        updateMetrics(dashboardData.metrics);
        createPowerChart(dashboardData.timeseries);
        createPhaseChart(dashboardData.metrics);
        createPowerFactorChart(dashboardData.metrics);
        createEventChart(dashboardData.events);
        populateEventsTable(dashboardData.events);
        
    } catch (error) {
        console.error('Error loading data:', error);
        showError(`Failed to load data: ${error.message}`);
    }
});

// Export for use in Jupyter/external updates
window.energyDashboard = {
    updateMetrics,
    createPowerChart,
    createPhaseChart,
    createPowerFactorChart,
    createEventChart,
    populateEventsTable,
    colors,
    API_BASE
};
