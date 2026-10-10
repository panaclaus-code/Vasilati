import io
import streamlit as st
import folium
from streamlit_folium import st_folium
from pyproj import Transformer
import pandas as pd
import osmnx as ox
from shapely.geometry import Polygon

# Configurarea paginii
st.set_page_config(page_title="Hartă Vasilați", layout="wide")

# --- TEXT EXPLICATIV DEASUPRA HĂRȚII ---
st.title("🌾 Hartă Vasilați")
st.markdown("""
**Aplicația ta de teren pentru zona Vasilați, Călărași.**
* 🗺️ **Harta & Straturile:** Poți comuta pe vizualizarea din satelit și poți urmări drumurile agricole (linii maronii) și canalele/apa (linii albastre).
* 📍 **Coordonate:** Dă click oriunde pe hartă pentru coordonatele GPS și transformarea lor în sistemul național **Stereo 70**.
* 📁 **Măsurători:** Încarcă din bara laterală un fișier CSV cu puncte topografice pentru a genera poligonul parcelei și suprafața în hectare.
""")

st.markdown("---")

# Transformator WGS84 -> Stereo 70 (returnează Est, Nord)
transformer_to_stereo = Transformer.from_crs("EPSG:4326", "EPSG:3844", always_xy=True)

# Coordonate centrate pe Vasilați, Călărași
LAT_CENTRU = 44.3167
LON_CENTRU = 26.3833

# --- BARĂ LATERALĂ: SETĂRI ȘI IMPORT ---
st.sidebar.header("📁 Import & Opțiuni")
uploaded_file = st.sidebar.file_uploader(
    "Încarcă fișier CSV cu puncte (coloane: Nume, Lat, Lon)",
    type=["csv", "txt"],
)

st.sidebar.markdown("---")
st.sidebar.subheader("🗺️ Straturi Tematice")
show_roads = st.sidebar.checkbox("Afișează drumuri agricole", value=True)
show_water = st.sidebar.checkbox("Afișează hidrografie (ape)", value=True)

# Crearea hărții interactive
m = folium.Map(
    location=[LAT_CENTRU, LON_CENTRU],
    zoom_start=14,
    tiles="CartoDB positron",
)

# Strat satelit Esri
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri",
    name="Satelit Esri",
    overlay=False,
    control=True,
).add_to(m)


# --- ÎNCĂRCARE AUTOMATĂ DRUMURI ȘI APE DIN OSM ---
@st.cache_data
def load_osm_features(lat, lon, dist=3000):
    point = (lat, lon)
    roads_gdf = None
    water_gdf = None
    try:
        roads_gdf = ox.features_from_point(
            point,
            tags={"highway": ["track", "path", "unpaved", "service", "secondary", "tertiary"]},
            dist=dist,
        )
    except Exception:
        pass

    try:
        water_gdf = ox.features_from_point(
            point,
            tags={"waterway": True, "natural": "water", "water": True},
            dist=dist,
        )
    except Exception:
        pass

    return roads_gdf, water_gdf


with st.spinner("Se încarcă elementele geografice din zonă..."):
    roads, water = load_osm_features(LAT_CENTRU, LON_CENTRU)

if show_roads and roads is not None and not roads.empty:
    roads_lines = roads[roads.geometry.type.isin(["LineString", "MultiLineString"])]
    roads_lines = roads_lines[["geometry"]].reset_index(drop=True)
    if not roads_lines.empty:
        folium.GeoJson(
            roads_lines,
            name="Drumuri Agricole",
            style_function=lambda x: {"color": "#8B4513", "weight": 2, "dashArray": "5, 5"},
        ).add_to(m)

if show_water and water is not None and not water.empty:
    water_geom = water[~water.geometry.type.isin(["Point", "MultiPoint"])]
    water_geom = water_geom[["geometry"]].reset_index(drop=True)
    if not water_geom.empty:
        folium.GeoJson(
            water_geom,
            name="Hidrografie",
            style_function=lambda x: {
                "color": "#1E90FF",
                "weight": 2,
                "fillColor": "#1E90FF",
                "fillOpacity": 0.4,
            },
        ).add_to(m)

# --- PROCESARE FIȘIER PUNCTE ȘI CALCUL SUPRAFAȚĂ ---
points_for_polygon = []
stereo_points = []

if uploaded_file is not None:
    try:
        # Decodare: UTF-8 (cu sau fără BOM), altfel Windows-1250 (Excel românesc)
        raw = uploaded_file.getvalue()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1250", errors="replace")

        # Acceptă separator , sau ; și zecimale cu punct sau virgulă
        df = pd.read_csv(io.StringIO(text), sep=None, engine="python", decimal=",")
        df.columns = df.columns.str.strip().str.title()

        if "Lat" in df.columns and "Lon" in df.columns:
            df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
            df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")
            df = df.dropna(subset=["Lat", "Lon"]).reset_index(drop=True)

            name_col = "Nume" if "Nume" in df.columns else None

            for index, row in df.iterrows():
                lat = float(row["Lat"])
                lon = float(row["Lon"])
                nume = str(row[name_col]) if name_col else f"Punct {index + 1}"

                # transform(lon, lat) -> (Est, Nord)
                est, nord = transformer_to_stereo.transform(lon, lat)
                stereo_points.append((est, nord))

                folium.CircleMarker(
                    location=[lat, lon],
                    radius=5,
                    color="red",
                    fill=True,
                    fill_color="red",
                    popup=(
                        f"<b>{nume}</b><br>Lat: {lat}, Lon: {lon}"
                        f"<br>X (Nord): {nord:.2f}, Y (Est): {est:.2f}"
                    ),
                ).add_to(m)

                points_for_polygon.append([lat, lon])

            if points_for_polygon:
                m.fit_bounds(points_for_polygon)

            if len(points_for_polygon) >= 3:
                folium.Polygon(
                    locations=points_for_polygon,
                    color="blue",
                    weight=3,
                    fill=True,
                    fill_color="blue",
                    fill_opacity=0.2,
                    popup="Parcelă Importată",
                ).add_to(m)

                poly = Polygon(stereo_points)
                arie_mp = poly.area
                arie_ha = arie_mp / 10000
                perimetru_m = poly.length

                st.sidebar.markdown("---")
                st.sidebar.subheader("📐 Raport Parcelă")

                if not poly.is_valid:
                    st.sidebar.warning(
                        "Poligon invalid (laturi care se intersectează). "
                        "Verifică ordinea punctelor în fișier, altfel suprafața e greșită."
                    )

                st.sidebar.success(f"**Suprafață:** {arie_mp:,.2f} mp\n\n({arie_ha:.4f} hectare)")
                st.sidebar.info(f"**Perimetru:** {perimetru_m:,.2f} metri")
            elif len(points_for_polygon) > 0:
                st.sidebar.info("Sunt necesare minim 3 puncte pentru a calcula suprafața.")
        else:
            st.sidebar.error("Fișierul trebuie să conțină coloanele 'Lat' și 'Lon'.")
    except Exception as e:
        st.sidebar.error(f"Eroare la procesarea fișierului: {e}")

folium.LayerControl().add_to(m)

# Afișarea hărții
st.subheader("Harta Interactivă Vasilați:")
output = st_folium(
    m,
    use_container_width=True,
    height=500,
    returned_objects=["last_clicked"],
)

# Interacțiune click pe hartă
if output and output.get("last_clicked"):
    clicked_lat = output["last_clicked"]["lat"]
    clicked_lon = output["last_clicked"]["lng"]

    est, nord = transformer_to_stereo.transform(clicked_lon, clicked_lat)

    st.success("📍 **Punct selectat de pe hartă:**")
    col1, col2 = st.columns(2)
    with col1:
        st.code(f"WGS84 -> Lat: {clicked_lat:.6f}, Lon: {clicked_lon:.6f}")
    with col2:
        st.code(f"Stereo 70 -> X (Nord): {nord:.3f} m, Y (Est): {est:.3f} m")
