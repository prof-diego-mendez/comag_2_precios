from flask import Flask, request, send_file, jsonify, render_template
from flask_cors import CORS
import pandas as pd
import os
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)

# CORS configurado para producción
allowed_origins = os.environ.get('ALLOWED_ORIGINS', '*').split(',')
CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xlsx'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Tabla de descuentos
MARCAS = {
    "BIFERDIL": 5,
    "OSLO": 15,
    "BIOLOOK": 20,
    "DEPILISSIMA": 30,
    "NEWCOLOR": 15,
    "NAIL PROTECT": 15,
    "CAPRI": 20,
    "IYOSEI": 10,
    "DODDY": 15,
    "TAN NATURAL": 20
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def normalizar(x):
    """Normaliza el valor de la columna asignado"""
    return str(x).strip().split('.')[0]


def encontrar_filas(valor_pedido, precios_df, tiene_pvp, desc_col):
    """Busca coincidencias en la lista de precios"""
    match = precios_df[precios_df["asignado"] == valor_pedido]
    if match.empty:
        match = precios_df[precios_df["asignado"].str.contains(valor_pedido, na=False)]
    
    if not match.empty:
        row = match.iloc[0]
        precio = row["precio_sin_iva"]
        pvp = row["pvp"] if tiene_pvp else None
        desc = None
        if desc_col:
            texto = str(row[desc_col]).upper()
            for marca, dto in MARCAS.items():
                if marca in texto:
                    desc = dto
                    break
        return row["asignado"], precio, pvp, desc
    return None, None, None, None


def procesar_merge(lista_file, pedido_file, archivo_salida):
    """Procesa la fusión de los dos archivos Excel"""
    # Cargar archivos
    precios_df = pd.read_excel(lista_file)
    pedido_df = pd.read_excel(pedido_file)

    # Limpiar y normalizar columnas
    precios_df["asignado"] = precios_df["asignado"].apply(normalizar)
    pedido_df["asignado"] = pedido_df["asignado"].apply(normalizar)

    # Detectar columnas opcionales
    tiene_pvp = "pvp" in precios_df.columns
    desc_col = None
    for col in precios_df.columns:
        if precios_df[col].dtype == object:
            if precios_df[col].str.contains("|".join(MARCAS), case=False, na=False).any():
                desc_col = col
                break

    # Aplicar y crear columnas
    pedido_df[["asignado_lista", "precio", "pvp", "descuento"]] = pedido_df["asignado"].apply(
        lambda x: pd.Series(encontrar_filas(x, precios_df, tiene_pvp, desc_col))
    )

    # Si no hay descuentos, eliminar columna
    if pedido_df["descuento"].isna().all():
        pedido_df.drop(columns=["descuento"], inplace=True)

    # Guardar resultado
    pedido_df.to_excel(archivo_salida, index=False)
    return archivo_salida


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/procesar', methods=['POST'])
def procesar():
    if 'archivo_lista' not in request.files or 'archivo_pedido' not in request.files:
        return jsonify({'error': 'Se requieren ambos archivos: lista de precios y pedido'}), 400

    file_lista = request.files['archivo_lista']
    file_pedido = request.files['archivo_pedido']

    if file_lista.filename == '' or file_pedido.filename == '':
        return jsonify({'error': 'Debe seleccionar ambos archivos'}), 400

    if not allowed_file(file_lista.filename) or not allowed_file(file_pedido.filename):
        return jsonify({'error': 'Formato no válido. Solo se permiten archivos .xlsx'}), 400

    try:
        # Generar nombres únicos para los archivos
        unique_id = uuid.uuid4().hex
        
        # Archivos de entrada
        filename_lista = secure_filename(file_lista.filename)
        filename_pedido = secure_filename(file_pedido.filename)
        
        archivo_lista = os.path.join(UPLOAD_FOLDER, f"{unique_id}_lista_{filename_lista}")
        archivo_pedido = os.path.join(UPLOAD_FOLDER, f"{unique_id}_pedido_{filename_pedido}")
        
        # Nombre de salida
        nombre_base_lista = filename_lista.rsplit('.', 1)[0]
        nombre_base_pedido = filename_pedido.rsplit('.', 1)[0]
        archivo_salida = os.path.join(UPLOAD_FOLDER, f"{unique_id}_{nombre_base_lista}_{nombre_base_pedido}_enriquecido.xlsx")

        # Guardar archivos temporales
        file_lista.save(archivo_lista)
        file_pedido.save(archivo_pedido)

        # Procesar la fusión
        resultado = procesar_merge(archivo_lista, archivo_pedido, archivo_salida)

        # Limpiar archivos de entrada
        os.remove(archivo_lista)
        os.remove(archivo_pedido)

        return jsonify({
            'success': True,
            'message': 'Archivos fusionados correctamente',
            'download_url': f'/api/descargar/{os.path.basename(resultado)}'
        })

    except Exception as e:
        return jsonify({'error': f'Error al procesar los archivos: {str(e)}'}), 500


@app.route('/api/descargar/<filename>')
def descargar(filename):
    return send_file(
        os.path.join(UPLOAD_FOLDER, filename),
        as_attachment=True
    )


@app.route('/api/limpiar', methods=['POST'])
def limpiar():
    """Limpia archivos temporales antiguos (más de 1 hora)"""
    import time
    ahora = time.time()
    eliminados = 0
    for archivo in os.listdir(UPLOAD_FOLDER):
        path = os.path.join(UPLOAD_FOLDER, archivo)
        if os.path.isfile(path) and (ahora - os.path.getmtime(path)) > 3600:
            os.remove(path)
            eliminados += 1
    return jsonify({'eliminados': eliminados})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
