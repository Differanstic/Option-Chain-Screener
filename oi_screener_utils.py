import pandas as pd
import numpy as np

from py_vollib_vectorized import (
    vectorized_implied_volatility,
    vectorized_delta,
    vectorized_gamma,
    vectorized_vega,
    vectorized_theta,
)

def calculate_greeks(df, r=0.1):

    df = df.copy()
    spot_map = df[df["strike_price"] == -1].set_index("timestamp")["ltp"]
    df["spot"] = df["timestamp"].map(spot_map)

    opt = df[
        (df["strike_price"] > 0) &
        (df["ltp"] > 0) &
        (df["spot"] > 0)
    ].copy()


    T = opt['expiry']
    opt = opt[T > 0.0001].copy()
    T = T[T > 0.0001]

    S = opt["spot"].values
    K = opt["strike_price"].values
    price = opt["ltp"].values

    flag = opt["option_type"].str.lower().map({"ce": "c", "pe": "p"}).values

    # intrinsic value
    intrinsic = np.maximum(
        np.where(flag == "c", S - K, K - S),
        0
    )

    # remove invalid price
    valid = (price >= intrinsic) | (price == -1)

    opt = opt[valid]
    price = price[valid]
    S = S[valid]
    K = K[valid]
    T = T[valid]
    flag = flag[valid]

    # calculate safely
    try:
        iv = vectorized_implied_volatility(
            price, S, K, T, r, flag,
            on_error="ignore",
            return_as="numpy"
        )
    except:
        iv = np.full_like(price, np.nan)

    delta = vectorized_delta(flag, S, K, T, r, iv, return_as="numpy")
    gamma = vectorized_gamma(flag, S, K, T, r, iv, return_as="numpy")
    vega  = vectorized_vega(flag, S, K, T, r, iv, return_as="numpy")
    theta = vectorized_theta(flag, S, K, T, r, iv, return_as="numpy")

    opt["iv"] = iv
    opt["delta"] = delta
    opt["gamma"] = gamma
    opt["vega"] = vega
    opt["theta"] = theta
    opt['spot_price']= S
    sign = np.where(opt["option_type"].str.upper() == "CE", 1, -1)
    opt['delta_exp'] = delta * opt['oi'] * opt['spot_price'] 
    opt['gamma_exp'] = gamma * opt['oi'] * opt['spot_price'] 
    opt['vega_exp']  = vega  * opt['oi'] * opt['spot_price'] 
    opt['theta_exp'] = theta * opt['oi'] * opt['spot_price'] 
    
    

    # merge back
    df = df.merge(
        opt[[
            "timestamp",
            "strike_price",
            "iv",
            "delta",
            "gamma",
            "vega",
            "theta",
            "gamma_exp",
            "delta_exp",
            "vega_exp",
            "theta_exp",
            'spot_price'
        ]],
        on=["timestamp","strike_price"],
        how="left"
    )

    net_exposure = opt.groupby("timestamp").agg({
        "gamma_exp": "sum",
        "delta_exp": "sum",
        "vega_exp": "sum",
        "theta_exp": "sum"
    }).rename(columns={
        "gamma_exp": "net_gamma_exp",
        "delta_exp": "net_delta_exp",
        "vega_exp": "net_vega_exp",
        "theta_exp": "net_theta_exp"
    })

    # merge net exposure back
    df = df.merge(net_exposure, on="timestamp", how="left")
    
    
    ### MaX pain 
    
    
    
    return df

from scipy.stats import norm



def implied_volatility(option_price, S, K, T, r, option_type):
    if option_price <= 0 or T <= 0:
        return 0

    sigma = 0.2  # initial guess

    for _ in range(50):
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        if option_type == "CE":
            price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

        vega = S * norm.pdf(d1) * np.sqrt(T)

        if vega < 1e-6:
            break

        sigma -= (price - option_price) / vega

        if sigma <= 0:
            sigma = 0.0001

    return sigma



def bs_greeks(S, K, T, r, iv, opt_type):
    if T <= 0 or iv <= 0:
        return 0, 0, 0, 0

    d1 = (np.log(S / K) + (r + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
    d2 = d1 - iv * np.sqrt(T)

    delta = norm.cdf(d1) if opt_type == "CE" else -norm.cdf(-d1)
    gamma = norm.pdf(d1) / (S * iv * np.sqrt(T)) 
    if opt_type == 'PE':
        gamma = -gamma
    vega  = S * norm.pdf(d1) * np.sqrt(T) / 100
    theta = -S * norm.pdf(d1) * iv / (2 * np.sqrt(T)) / 365

    return delta, gamma, vega, theta
