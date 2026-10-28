"""Plot an already-computed use profile without changing numerical data."""
import numpy as np
import pandas as pd
TEAL = "#00B1A8"
NAVY = "#193c50"

def plot_use_profile(profile, *, labels=None):
    import plotly.graph_objects as go
    shares, uses, total = profile.shares.T, profile.amounts.T, profile.totals
    product = profile.product
    labels = labels or {}
    custom = np.empty((*shares.shape, 4), dtype=object)
    custom[:, :, 0] = uses.to_numpy()
    custom[:, :, 1] = np.broadcast_to(total.to_numpy()[:, None], shares.shape)
    custom[:, :, 2] = np.broadcast_to([labels.get(c, c) for c in shares.columns], shares.shape)
    custom[:, :, 3] = uses.map(lambda q: f" ({q * 1e6:.3g} USD)" if pd.notna(q) and abs(q) < .001 else "").to_numpy()
    material = shares.where(uses < -1e-6)
    minimum = float(material.min().min()) if material.notna().any().any() else 0
    zero_position = -minimum / (100 - minimum) if minimum < 0 else 0
    colors = ([[0, "#b2182b"], [zero_position, "#f2f7f7"],
               [zero_position + .1 * (1 - zero_position), "#a9ded8"],
               [zero_position + .4 * (1 - zero_position), TEAL], [1, NAVY]]
              if minimum < 0 else [[0, "#f2f7f7"], [.1, "#a9ded8"], [.4, TEAL], [1, NAVY]])
    fig = go.Figure(go.Heatmap(
        z=shares.T.to_numpy().tolist(), x=shares.index.tolist(), y=shares.columns.tolist(),
        customdata=custom.transpose(1, 0, 2).tolist(), zmin=min(0, minimum), zmax=100,
        colorscale=colors,
        colorbar=dict(title="Use (%)", lenmode="pixels", len=300, y=1, yanchor="top"), hoverongaps=False,
        hovertemplate="%{x}<br>%{y} · %{customdata[2]}<br>%{z:.6g}% of selected use"
                      "<br>Use: %{customdata[0]:,.4f} M USD%{customdata[3]}"
                      "<br>Selected regional total: %{customdata[1]:,.4f} M USD<extra></extra>"))
    fig.update_layout(template="plotly_white", title=dict(text=f"Who uses {product}? · {labels.get(product, product)}",
                                 x=.14, y=.997, yanchor="top", font=dict(size=18)),
                      width=1100, height=16 * len(shares.columns) + 200,
                      margin=dict(l=155, r=95, t=170, b=35),
                      xaxis=dict(tickmode="array", tickvals=shares.index.tolist(), tickangle=-60,
                                 tickfont=dict(size=11), side="top"),
                      yaxis=dict(autorange="reversed", title="Using sector / final consumer",
                                 tickmode="array", tickvals=shares.columns.tolist(), tickfont=dict(size=10)),
                      plot_bgcolor="#dedede", font=dict(family="Arial", color=NAVY))
    return fig
