"""Run: streamlit run app.py"""
from datetime import date
import streamlit as st
import streamlit.components.v1 as components
from core import AIRPORTS, GEOD, calculate, make_svg, parse_point

st.set_page_config(page_title="ECALC PoC", page_icon="🧭", layout="wide")
st.title("ECALC · WGS-84")
st.caption("Прототип расчёта расстояний и азимутов от контрольной точки аэродрома. Не для навигации.")

with st.sidebar:
    st.header("Параметры")
    airport = st.selectbox("Аэродром", list(AIRPORTS), index=list(AIRPORTS).index("UCFT (Талас)"))
    if "airport_choice" not in st.session_state or airport != st.session_state.airport_choice:
        st.session_state.airport_choice = airport
        st.session_state.base = AIRPORTS[airport]
    base = st.text_input("Координаты КТА", key="base", placeholder="N423101 E0721448")
    bearing = st.radio("Азимут", ["Magnetic", "True"], horizontal=True)
    precision = st.radio("Точность", ["Целые", "2 знака"], horizontal=True)
    units = st.radio("Дистанция", ["km", "nm"], horizontal=True)
    mode = st.radio("Формат", ["Вставка в текст", "Чистый список"])
    year = st.number_input("Год магнитной модели", min_value=2025.0, max_value=2030.0,
                           value=float(date.today().year), step=0.1,
                           help="Дата должна попадать в период действия установленной магнитной модели.")

example = "(Т.1) N423101 E0721448\n(Т.2) N423520 E0723000\n(Т.3) N422800 E0724000\n(Т.1) N423101 E0721448"
st.subheader("Входные данные")
source = st.text_area("Список координат или текст", height=170, placeholder=example)

if source.strip():
    try:
        result = calculate(base, source, magnetic=bearing=="Magnetic",
                           decimals=precision=="2 знака", nautical_miles=units=="nm",
                           clean_list=mode=="Чистый список", year=year)
    except (ValueError, RuntimeError, ImportError, OSError) as exc:
        st.error(f"Не удалось выполнить расчёт: {exc}")
        st.stop()
    for warning in result.warnings:
        st.warning(warning)
    if not result.points:
        st.info("Не найдено корректных точек для расчёта.")
    st.subheader("Результаты")
    st.text_area("Расчётный текст", value=result.text, height=220)
    st.download_button("Скачать TXT", data=result.text.encode("utf-8"), file_name="ECALC-result.txt",
                       mime="text/plain", disabled=not result.text)
    st.info(f"Топология: {result.topology}")
    with st.expander("Графическая схема", expanded=True):
        view_mode = st.radio(
            "Масштаб схемы",
            ["Все объекты", "Только граница"],
            horizontal=True,
            help="В режиме «Только граница» удалённая КТА может оказаться за пределами схемы. На расчёты это не влияет.",
        )
        # Render in an iframe: st.html sanitizes content and can suppress inline SVG.
        # A full HTML document also makes the SVG reliably visible across themes.
        svg = make_svg(parse_point(base), result.points, focus_boundary=view_mode == "Только граница")
        components.html(
            f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
            <style>html,body{{margin:0;padding:0;background:transparent;overflow:hidden}}
            svg{{display:block;width:100%;height:auto;max-height:520px}}</style>
            </head><body>{svg}</body></html>""",
            height=520,
            scrolling=False,
        )
        st.caption("Условная плоская схема, не авиационная карта. Проверяется только замыкание, не самопересечение.")
    with st.expander("Сводка по точкам"):
        base_lat, base_lon = parse_point(base)
        table = []
        for number, point in enumerate(result.points, start=1):
            distance = GEOD.Inverse(base_lat, base_lon, point.lat, point.lon)["s12"]
            table.append({
                "№": number,
                "Название": point.label,
                "Широта": round(point.lat, 6),
                "Долгота": round(point.lon, 6),
                "От КТА, км": round(distance / 1000, 2),
            })
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.caption("Повторяющаяся замыкающая точка показывается отдельной строкой.")
else:
    st.info("Вставьте координаты выше. Например:\n\n" + example)
