/* Afficher / masquer un mot de passe.
 *
 * Symptôme corrigé : le bouton disparaissait après la saisie. Cause : il était
 * positionné en absolu par-dessus le champ, et sur mobile la barre de
 * navigation du clavier le poussait hors du cadre visible. Ici le bouton est
 * un élément du input-group Bootstrap, donc il occupe toujours sa place dans
 * le flux quel que soit l'écran, et sa zone cliquable fait 44 px (tactile).
 *
 * Sans dépendance, avec délégation d'événement : fonctionne même si les
 * champs sont injectés plus tard par du JavaScript.
 */
(function () {
    'use strict';

    var ICONE = {
        visible: 'visibility',
        masque: 'visibility_off'
    };

    function basculer(bouton) {
        var champ = document.getElementById(bouton.getAttribute('data-cible'));
        if (!champ) { return; }

        var seraVisible = champ.type === 'password';
        champ.type = seraVisible ? 'text' : 'password';

        var icone = bouton.querySelector('.material-symbols-outlined');
        if (icone) { icone.textContent = seraVisible ? ICONE.visible : ICONE.masque; }

        bouton.setAttribute('aria-pressed', seraVisible ? 'true' : 'false');
        bouton.setAttribute('aria-label',
            seraVisible ? 'Masquer le mot de passe' : 'Afficher le mot de passe');
        bouton.setAttribute('title',
            seraVisible ? 'Masquer le mot de passe' : 'Afficher le mot de passe');

        // Le focus reste sur le champ : on peut continuer à taper sans reprendre
        // la souris ni perdre le clavier ouvert sur mobile.
        champ.focus({ preventScroll: true });
        var n = champ.value.length;
        try { champ.setSelectionRange(n, n); } catch (e) { /* type non text */ }
    }

    document.addEventListener('click', function (ev) {
        var bouton = ev.target.closest ? ev.target.closest('[data-bascule-mdp]') : null;
        if (!bouton) { return; }
        ev.preventDefault();
        basculer(bouton);
    });
}());