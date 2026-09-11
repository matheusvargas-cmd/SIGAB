// Gabinete 360 — landing page comercial (/). JS mínimo, isolado do
// restante do sistema: só o menu mobile e o accordion do FAQ, nenhuma
// dependência de biblioteca externa nem de código já existente.
(function () {
    var botaoMenu = document.querySelector('[data-menu-toggle]');
    var menuMobile = document.querySelector('[data-menu-mobile]');
    if (botaoMenu && menuMobile) {
        botaoMenu.addEventListener('click', function () {
            var aberto = menuMobile.getAttribute('data-aberto') === 'true';
            menuMobile.setAttribute('data-aberto', aberto ? 'false' : 'true');
        });
        // Ao navegar por um link do menu mobile (ancora da própria
        // página), fecha o menu — sem isso ele continuaria aberto,
        // sobrepondo a seção para a qual o usuário acabou de navegar.
        menuMobile.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', function () {
                menuMobile.setAttribute('data-aberto', 'false');
            });
        });
    }

    document.querySelectorAll('[data-faq-item]').forEach(function (item) {
        var pergunta = item.querySelector('[data-faq-pergunta]');
        if (!pergunta) {
            return;
        }
        pergunta.addEventListener('click', function () {
            var aberto = item.getAttribute('data-aberto') === 'true';
            item.setAttribute('data-aberto', aberto ? 'false' : 'true');
        });
    });
})();
