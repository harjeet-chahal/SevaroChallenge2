{{/* Chart name, truncated to the 63-character DNS label limit. */}}
{{- define "sevaro-pulse.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Release fullname: "<release>" if it already contains the chart name, else "<release>-<chart>". */}}
{{- define "sevaro-pulse.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "sevaro-pulse.backend.fullname" -}}
{{- printf "%s-backend" (include "sevaro-pulse.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sevaro-pulse.frontend.fullname" -}}
{{- printf "%s-frontend" (include "sevaro-pulse.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sevaro-pulse.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Labels shared by every object. */}}
{{- define "sevaro-pulse.labels" -}}
helm.sh/chart: {{ include "sevaro-pulse.chart" . }}
app.kubernetes.io/name: {{ include "sevaro-pulse.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: sevaro-pulse
{{- end }}

{{/* Selector labels for one component. Usage: include "sevaro-pulse.selectorLabels" (dict "ctx" . "component" "backend") */}}
{{- define "sevaro-pulse.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sevaro-pulse.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "sevaro-pulse.componentLabels" -}}
{{ include "sevaro-pulse.labels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "sevaro-pulse.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "sevaro-pulse.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* "<repository>:<tag>", with the tag defaulting to the chart appVersion. Usage: include "sevaro-pulse.image" (dict "image" .Values.backend.image "ctx" .) */}}
{{- define "sevaro-pulse.image" -}}
{{- printf "%s:%s" .image.repository (default .ctx.Chart.AppVersion .image.tag | toString) }}
{{- end }}

{{- define "sevaro-pulse.backend.pvcName" -}}
{{- default (printf "%s-data" (include "sevaro-pulse.backend.fullname" .)) .Values.backend.persistence.existingClaim }}
{{- end }}

{{- define "sevaro-pulse.backend.dbSecretName" -}}
{{- default (printf "%s-db" (include "sevaro-pulse.backend.fullname" .)) .Values.backend.database.external.existingSecret }}
{{- end }}

{{/* True when the backend keeps SQLite on local storage. */}}
{{- define "sevaro-pulse.backend.sqlite" -}}
{{- if not .Values.backend.database.external.enabled }}true{{- end }}
{{- end }}

{{/* Fail fast on settings that would corrupt data or never work. */}}
{{- define "sevaro-pulse.validate" -}}
{{- $be := .Values.backend }}
{{- if and (include "sevaro-pulse.backend.sqlite" .) (gt (int $be.replicaCount) 1) }}
{{- fail "backend.replicaCount must be 1 with SQLite (single writer, per-process caches). Enable backend.database.external first." }}
{{- end }}
{{- if and $be.database.external.enabled (not $be.database.external.existingSecret) (not $be.database.external.url) }}
{{- fail "backend.database.external.enabled needs existingSecret or url." }}
{{- end }}
{{- if and .Values.ingress.tls.enabled (not .Values.ingress.tls.secretName) }}
{{- fail "ingress.tls.enabled needs ingress.tls.secretName." }}
{{- end }}
{{- if and .Values.ingress.tls.enabled (not .Values.ingress.host) }}
{{- fail "ingress.tls.enabled needs ingress.host (a certificate is issued for a name)." }}
{{- end }}
{{- end }}
