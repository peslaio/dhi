{{- define "dhi.common.serviceAccount" -}}
{{- if .Values.serviceAccount.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "dhi.common.serviceAccountName" . }}
  labels:
    {{- include "dhi.common.labels" . | nindent 4 }}
  {{- with .Values.serviceAccount.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
automountServiceAccountToken: {{ .Values.serviceAccount.automountServiceAccountToken }}
{{- end }}
{{- end -}}

{{- define "dhi.common.configMap" -}}
{{- if .Values.config.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "dhi.common.fullname" . }}
  labels:
    {{- include "dhi.common.labels" . | nindent 4 }}
data:
  {{- range $key, $value := .Values.config.data }}
  {{ $key }}: |-
    {{- $value | nindent 4 }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "dhi.common.pvc" -}}
{{- if and .Values.persistence.enabled (not .Values.persistence.existingClaim) (not (and (eq (default "deployment" .Values.workload.type) "statefulset") .Values.persistence.volumeClaimTemplate)) }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "dhi.common.fullname" . }}
  labels:
    {{- include "dhi.common.labels" . | nindent 4 }}
  {{- with .Values.persistence.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  accessModes:
    {{- toYaml .Values.persistence.accessModes | nindent 4 }}
  {{- if .Values.persistence.storageClass }}
  storageClassName: {{ .Values.persistence.storageClass | quote }}
  {{- end }}
  resources:
    requests:
      storage: {{ .Values.persistence.size | quote }}
{{- end }}
{{- end -}}

{{- define "dhi.common.service" -}}
{{- if .Values.service.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "dhi.common.fullname" . }}
  labels:
    {{- include "dhi.common.labels" . | nindent 4 }}
  {{- with .Values.service.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  type: {{ .Values.service.type }}
  {{- with .Values.service.clusterIP }}
  clusterIP: {{ . | quote }}
  {{- end }}
  {{- with .Values.service.publishNotReadyAddresses }}
  publishNotReadyAddresses: {{ . }}
  {{- end }}
  ports:
    {{- range .Values.service.ports }}
    - name: {{ .name }}
      port: {{ .port }}
      targetPort: {{ .targetPort | default .name }}
      protocol: {{ .protocol | default "TCP" }}
      {{- with .nodePort }}
      nodePort: {{ . }}
      {{- end }}
    {{- end }}
  selector:
    {{- include "dhi.common.selectorLabels" . | nindent 4 }}
{{- end }}
{{- end -}}

{{- define "dhi.common.workload" -}}
apiVersion: apps/v1
kind: {{ include "dhi.common.workloadKind" . }}
metadata:
  name: {{ include "dhi.common.fullname" . }}
  labels:
    {{- include "dhi.common.labels" . | nindent 4 }}
  {{- with .Values.commonAnnotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- if eq (default "deployment" .Values.workload.type) "statefulset" }}
  serviceName: {{ include "dhi.common.fullname" . }}
  {{- end }}
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "dhi.common.selectorLabels" . | nindent 6 }}
  {{- if and (eq (default "deployment" .Values.workload.type) "deployment") .Values.updateStrategy }}
  strategy:
    {{- toYaml .Values.updateStrategy | nindent 4 }}
  {{- end }}
  {{- if and (eq (default "deployment" .Values.workload.type) "statefulset") .Values.updateStrategy }}
  updateStrategy:
    {{- toYaml .Values.updateStrategy | nindent 4 }}
  {{- end }}
  {{- if and (eq (default "deployment" .Values.workload.type) "statefulset") .Values.persistence.enabled (not .Values.persistence.existingClaim) .Values.persistence.volumeClaimTemplate }}
  volumeClaimTemplates:
    - metadata:
        name: data
        labels:
          {{- include "dhi.common.labels" . | nindent 10 }}
        {{- with .Values.persistence.annotations }}
        annotations:
          {{- toYaml . | nindent 10 }}
        {{- end }}
      spec:
        accessModes:
          {{- toYaml .Values.persistence.accessModes | nindent 10 }}
        {{- if .Values.persistence.storageClass }}
        storageClassName: {{ .Values.persistence.storageClass | quote }}
        {{- end }}
        resources:
          requests:
            storage: {{ .Values.persistence.size | quote }}
  {{- end }}
  template:
    metadata:
      labels:
        {{- include "dhi.common.selectorLabels" . | nindent 8 }}
        {{- with .Values.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      {{- with .Values.podAnnotations }}
      annotations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
    spec:
      serviceAccountName: {{ include "dhi.common.serviceAccountName" . }}
      automountServiceAccountToken: {{ .Values.serviceAccount.automountServiceAccountToken }}
      {{- with .Values.image.pullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- if .Values.podSecurityContext.enabled }}
      {{- $podSecurityContext := omit .Values.podSecurityContext "enabled" -}}
      {{- if .Values.openshift.enabled }}
      {{- $podSecurityContext = omit $podSecurityContext "fsGroup" "fsGroupChangePolicy" -}}
      {{- end }}
      {{- if $podSecurityContext }}
      securityContext:
        {{- $podSecurityContext | toYaml | nindent 8 }}
      {{- end }}
      {{- end }}
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.topologySpreadConstraints }}
      topologySpreadConstraints:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.priorityClassName }}
      priorityClassName: {{ . | quote }}
      {{- end }}
      {{- with .Values.initContainers }}
      initContainers:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: {{ include "dhi.common.name" . }}
          image: {{ include "dhi.common.image" . | quote }}
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          {{- with .Values.command }}
          command:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.args }}
          args:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- if .Values.containerSecurityContext.enabled }}
          {{- $containerSecurityContext := omit .Values.containerSecurityContext "enabled" -}}
          {{- if .Values.openshift.enabled }}
          {{- $containerSecurityContext = omit $containerSecurityContext "runAsUser" "runAsGroup" -}}
          {{- end }}
          {{- if $containerSecurityContext }}
          securityContext:
            {{- $containerSecurityContext | toYaml | nindent 12 }}
          {{- end }}
          {{- end }}
          {{- with .Values.containerPorts }}
          ports:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- if or .Values.env .Values.extraEnvVars }}
          env:
            {{- range $key, $value := .Values.env }}
            - name: {{ $key }}
              value: {{ tpl ($value | toString) $ | quote }}
            {{- end }}
            {{- with .Values.extraEnvVars }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
          {{- end }}
          {{- if or .Values.extraEnvVarsCM .Values.extraEnvVarsSecret .Values.extraEnvFrom }}
          envFrom:
            {{- with .Values.extraEnvVarsCM }}
            - configMapRef:
                name: {{ . }}
            {{- end }}
            {{- with .Values.extraEnvVarsSecret }}
            - secretRef:
                name: {{ . }}
            {{- end }}
            {{- with .Values.extraEnvFrom }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
          {{- end }}
          {{- if .Values.livenessProbe.enabled }}
          livenessProbe:
            {{- omit .Values.livenessProbe "enabled" | toYaml | nindent 12 }}
          {{- end }}
          {{- if .Values.readinessProbe.enabled }}
          readinessProbe:
            {{- omit .Values.readinessProbe "enabled" | toYaml | nindent 12 }}
          {{- end }}
          {{- if .Values.startupProbe.enabled }}
          startupProbe:
            {{- omit .Values.startupProbe "enabled" | toYaml | nindent 12 }}
          {{- end }}
          {{- with .Values.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.lifecycle }}
          lifecycle:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- if or .Values.config.enabled .Values.persistence.enabled .Values.emptyDirs .Values.extraVolumeMounts }}
          volumeMounts:
            {{- if .Values.config.enabled }}
            - name: config
              mountPath: {{ .Values.config.mountPath }}
              subPath: {{ .Values.config.filename }}
              readOnly: true
            {{- end }}
            {{- if .Values.persistence.enabled }}
            - name: data
              mountPath: {{ .Values.persistence.mountPath }}
            {{- end }}
            {{- range .Values.emptyDirs }}
            - name: {{ .name }}
              mountPath: {{ .mountPath }}
            {{- end }}
            {{- with .Values.extraVolumeMounts }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
          {{- end }}
        {{- with .Values.sidecars }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      {{- if or .Values.config.enabled .Values.persistence.enabled .Values.emptyDirs .Values.extraVolumes }}
      volumes:
        {{- if .Values.config.enabled }}
        - name: config
          configMap:
            name: {{ include "dhi.common.fullname" . }}
        {{- end }}
        {{- if and .Values.persistence.enabled (or .Values.persistence.existingClaim (not (and (eq (default "deployment" .Values.workload.type) "statefulset") .Values.persistence.volumeClaimTemplate))) }}
        - name: data
          persistentVolumeClaim:
            claimName: {{ default (include "dhi.common.fullname" .) .Values.persistence.existingClaim }}
        {{- end }}
        {{- range .Values.emptyDirs }}
        - name: {{ .name }}
          {{- $emptyDir := omit . "name" "mountPath" }}
          {{- if $emptyDir }}
          emptyDir:
            {{- $emptyDir | toYaml | nindent 12 }}
          {{- else }}
          emptyDir: {}
          {{- end }}
        {{- end }}
        {{- with .Values.extraVolumes }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      {{- end }}
{{- end -}}

{{- define "dhi.common.hpa" -}}
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "dhi.common.fullname" . }}
  labels:
    {{- include "dhi.common.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: {{ include "dhi.common.workloadKind" . }}
    name: {{ include "dhi.common.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    {{- toYaml .Values.autoscaling.metrics | nindent 4 }}
{{- end }}
{{- end -}}

{{- define "dhi.common.networkPolicy" -}}
{{- if .Values.networkPolicy.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "dhi.common.fullname" . }}
  labels:
    {{- include "dhi.common.labels" . | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      {{- include "dhi.common.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
    {{- if .Values.networkPolicy.egress }}
    - Egress
    {{- end }}
  ingress:
    {{- if .Values.networkPolicy.allowExternal }}
    {{- if and .Values.service.enabled .Values.service.ports }}
    - ports:
        {{- range .Values.service.ports }}
        - port: {{ .targetPort | default .port }}
          protocol: {{ .protocol | default "TCP" }}
        {{- end }}
    {{- else }}
    - {}
    {{- end }}
    {{- else if .Values.networkPolicy.ingress }}
      {{- toYaml .Values.networkPolicy.ingress | nindent 4 }}
    {{- else }}
    []
    {{- end }}
  {{- with .Values.networkPolicy.egress }}
  egress:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "dhi.common.pdb" -}}
{{- if .Values.pdb.create }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "dhi.common.fullname" . }}
  labels:
    {{- include "dhi.common.labels" . | nindent 4 }}
spec:
  {{- if .Values.pdb.minAvailable }}
  minAvailable: {{ .Values.pdb.minAvailable }}
  {{- end }}
  {{- if .Values.pdb.maxUnavailable }}
  maxUnavailable: {{ .Values.pdb.maxUnavailable }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "dhi.common.selectorLabels" . | nindent 6 }}
{{- end }}
{{- end -}}

{{- define "dhi.common.ingress" -}}
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "dhi.common.fullname" . }}
  labels:
    {{- include "dhi.common.labels" . | nindent 4 }}
  {{- with .Values.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- with .Values.ingress.className }}
  ingressClassName: {{ . | quote }}
  {{- end }}
  {{- with .Values.ingress.tls }}
  tls:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  rules:
    {{- range .Values.ingress.hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          {{- range .paths }}
          - path: {{ .path }}
            pathType: {{ .pathType | default "Prefix" }}
            backend:
              service:
                name: {{ include "dhi.common.fullname" $ }}
                port:
                  name: {{ .servicePort | default "http" }}
          {{- end }}
    {{- end }}
{{- end }}
{{- end -}}

{{- define "dhi.common.render" -}}
{{- $resources := list (include "dhi.common.serviceAccount" .) (include "dhi.common.configMap" .) (include "dhi.common.pvc" .) (include "dhi.common.service" .) (include "dhi.common.workload" .) (include "dhi.common.hpa" .) (include "dhi.common.pdb" .) (include "dhi.common.ingress" .) (include "dhi.common.networkPolicy" .) -}}
{{- range $resource := $resources }}
{{- if ($resource | trim) }}
---
{{ $resource | trim }}
{{- end }}
{{- end }}
{{- end -}}
