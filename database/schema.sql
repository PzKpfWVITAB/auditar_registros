-- ========================================================
-- SCHEMA: SISTEMA DE AUDITORÍA DE REGISTROS POR OCR (MYSQL)
-- ========================================================

CREATE DATABASE IF NOT EXISTS `auditoria_registros` 
CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `auditoria_registros`;

-- Tabla de lotes o sesiones de auditoría
CREATE TABLE IF NOT EXISTS `lotes_auditoria` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `directorio_escaneado` VARCHAR(600) NOT NULL,
    `total_archivos` INT DEFAULT 0,
    `total_correctos` INT DEFAULT 0,
    `total_discrepancias` INT DEFAULT 0,
    `total_errores` INT DEFAULT 0,
    `fecha_inicio` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `fecha_fin` DATETIME NULL,
    `estado` VARCHAR(30) DEFAULT 'EN_PROCESO'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabla principal de documentos analizados
CREATE TABLE IF NOT EXISTS `documentos_auditados` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `lote_id` INT NULL,
    `nombre_archivo` VARCHAR(255) NOT NULL,
    `ruta_completa` VARCHAR(600) NOT NULL,
    `tamano_bytes` BIGINT DEFAULT 0,
    
    -- Metadatos extraídos del nombre de archivo actual
    `delegacion_actual` VARCHAR(10) NULL,
    `delegacion_archivo_nombre` VARCHAR(120) NULL,
    `anio_actual` INT NULL,
    `registro_actual` VARCHAR(20) NULL,
    
    -- Metadatos detectados por OCR espacial
    `delegacion_detectada_clave` VARCHAR(10) NULL,
    `municipio_detectado` VARCHAR(120) NULL,
    `delegacion_coincide` TINYINT(1) NULL,
    `confianza_delegacion` INT DEFAULT 0,
    `registro_encabezado` VARCHAR(20) NULL,
    `registro_pie` VARCHAR(20) NULL,
    `anio_detectado` INT NULL,
    `fecha_registro_texto` VARCHAR(150) NULL,
    `registro_antecedente` VARCHAR(50) NULL,
    
    -- Resolución y propuesta
    `registro_final_detectado` VARCHAR(20) NULL,
    `coincide_encabezado_pie` TINYINT(1) DEFAULT 0,
    `estado` ENUM('CORRECTO', 'DISCREPANCIA_REGISTRO', 'DISCREPANCIA_ANIO', 'DISCREPANCIA_DELEGACION', 'AMBAS_DISCREPANCIAS', 'ERROR_LECTURA', 'NOMBRE_INVALIDO') NOT NULL,
    `nombre_propuesto` VARCHAR(255) NULL,
    `confianza_score` INT DEFAULT 0,
    `motivo_discrepancia` TEXT NULL,
    `bounding_boxes_json` LONGTEXT NULL,
    
    -- Control operativo
    `tiempo_proceso_ms` INT DEFAULT 0,
    `colision_bd` TINYINT(1) DEFAULT 0,
    `estado_renombrado` ENUM('PENDIENTE', 'RENOMBRADO', 'OMITIDO') DEFAULT 'PENDIENTE',
    `fecha_auditoria` DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX `idx_estado` (`estado`),
    INDEX `idx_nombre_archivo` (`nombre_archivo`),
    INDEX `idx_registro_actual` (`registro_actual`),
    INDEX `idx_registro_final` (`registro_final_detectado`),
    INDEX `idx_colision_bd` (`colision_bd`),
    INDEX `idx_lote_id` (`lote_id`),
    INDEX `idx_fecha_auditoria` (`fecha_auditoria`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabla catálogo de PDFs existentes en la BD para detectar choques de nombre propuesto
CREATE TABLE IF NOT EXISTS `registros_existentes` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nombre_pdf` VARCHAR(255) NOT NULL,
    `fecha_carga` DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_nombre_pdf` (`nombre_pdf`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabla catálogo oficial de Delegaciones RPPC
CREATE TABLE IF NOT EXISTS `delegaciones` (
    `id` INT PRIMARY KEY,
    `nombre` VARCHAR(100) NOT NULL,
    `clave` VARCHAR(10) NOT NULL,
    `estatus` TINYINT(1) DEFAULT 1,
    UNIQUE KEY `uk_delegacion_clave` (`clave`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO `delegaciones` (`id`, `nombre`, `clave`, `estatus`) VALUES
(1, 'TUXTLA GUTIÉRREZ', '01', 1),
(2, 'SAN CRISTOBAL', '02', 1),
(3, 'VENUSTIANO CARRANZA', '03', 1),
(4, 'COMITAN', '04', 1),
(5, 'BOCHIL', '05', 1),
(6, 'COPAINALA', '06', 1),
(7, 'TONALA', '07', 1),
(8, 'TAPACHULA', '08', 1),
(9, 'CHIAPA DE CORZO', '09', 1),
(10, 'HUIXTLA', '10', 1),
(11, 'MOTOZINTLA', '11', 1),
(12, 'CINTALAPA', '12', 1),
(13, 'ACAPETAHUA', '13', 1),
(14, 'PICHUCALCO', '14', 1),
(15, 'VILLAFLORES', '15', 1),
(16, 'SALTO DE AGUA', '16', 1),
(17, 'CATAZAJA', '17', 1),
(18, 'OCOSINGO', '18', 1),
(19, 'YAJALON', '19', 1);

-- Tabla de historial de renombrado seguro (permite rollback si se activa)
CREATE TABLE IF NOT EXISTS `historial_renombrado` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `documento_id` INT NOT NULL,
    `nombre_original` VARCHAR(255) NOT NULL,
    `nombre_nuevo` VARCHAR(255) NOT NULL,
    `ruta_directorio` VARCHAR(600) NOT NULL,
    `fecha_accion` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `revertido` TINYINT(1) DEFAULT 0,
    FOREIGN KEY (`documento_id`) REFERENCES `documentos_auditados`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
