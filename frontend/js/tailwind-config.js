// Shared Tailwind CDN runtime configuration — loaded by all pages.
// k8s-dark is used by index.html; k8s-blue is used everywhere.
// devops-* tokens are additive: only labgen-catalog.html / labgen-lab.html /
// labgen-session.html (the learner-facing lab flow) opt into the dark
// DevOps-style palette. No existing page references these class names, so
// adding them here cannot change any other page's rendered output.
tailwind.config = {
    theme: {
        extend: {
            colors: {
                'k8s-blue': '#326CE5',
                'k8s-dark': '#1E293B',
                'devops-bg': '#0B0F17',
                'devops-surface': '#121826',
                'devops-surface-2': '#1A2233',
                'devops-border': '#232C3D',
                'devops-border-strong': '#2E3A52',
                'devops-text': '#E6EAF2',
                'devops-muted': '#8B96AC',
                'devops-faint': '#5B6478',
            },
            fontFamily: {
                'plex': ['"IBM Plex Sans"', '"IBM Plex Sans SC"', 'sans-serif'],
                'plex-mono': ['"JetBrains Mono"', '"Menlo"', 'monospace'],
            },
        }
    }
}
