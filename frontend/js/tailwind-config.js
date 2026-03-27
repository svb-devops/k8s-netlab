// Shared Tailwind CDN runtime configuration — loaded by all pages.
// k8s-dark is used by index.html; k8s-blue is used everywhere.
tailwind.config = {
    theme: {
        extend: {
            colors: {
                'k8s-blue': '#326CE5',
                'k8s-dark': '#1E293B',
            }
        }
    }
}
