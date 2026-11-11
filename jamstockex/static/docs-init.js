// Starts Swagger UI on /docs. A separate file, so the page's CSP needs no inline scripts.
window.addEventListener("load", function () {
  window.ui = SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    validatorUrl: null
  });
});
