<template>
  <a-layout-footer class="footer">
    <div class="footer-content">
      <p class="copyright">AI PPT创作器 ©2026</p>
    </div>
  </a-layout-footer>
</template>

<script setup lang="ts">
</script>

<style scoped>
.footer {
  background: var(--color-background);
  text-align: center;
  padding: 24px 20px;
  border-top: 1px solid var(--color-border);
}
.footer-content { max-width: 1200px; margin: 0 auto; }
.copyright { margin: 0; color: var(--color-text-muted); font-size: 13px; }
</style>
