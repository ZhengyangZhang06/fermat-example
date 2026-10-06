# Final root proof: height and rational factorization

This is the natural-language proof of the implemented route, submitted for independent review. It does not replace or edit the frozen natural-proof-v1.md geometric G/D/K outline. The additional reference was explicitly authorized in AGENTS.md. All library declarations below are unchanged upstream source, not newly invented child lemmas. The comparator-approved arithmetic/group children are historical decomposition work and are not dependencies of this route. Their original proof bodies in Submission.lean are preserved; this argument invokes none of them. A redundant triply nested copy of the finite-kernel child was removed after it caused a fatal namespace warning in the configured comparator.

## Exact hypotheses and notation

Let k be an algebraically closed field with decidable equality, p a prime natural number with CharP k p, W an elliptic Weierstrass curve, and A = W.toAffine.Point. Let beta be an additive endomorphism in the frozen rationalHomSet. For integers t,q assume beta composed with beta + [q] = t beta, m²-tm+q is nonzero for every integer m, p divides q, and p does not divide t. Here [n] is integer scalar multiplication on A; the conclusion uses the original natural-number scalar p.

## Numbered proof

1. Every coprime polynomial pair u,v of positive maximum degree can be written u=u0(X^(p^e)), v=v0(X^(p^e)), where u0,v0 remain coprime, have positive maximum degree, and have nonzero Wronskian. If the Wronskian is zero, coprimality implies both derivatives vanish; in characteristic p both polynomials are expansions by p. Contracting divides their positive maximum degree by p, so induction terminates. The exponent is unique for a fixed reduced fraction: two coprime representations differ by a common nonzero scalar. If one exponent were larger, injectivity of expansion would express the other residual pair as a positive p-power expansion, whose Wronskian vanishes, contradicting its nonzero Wronskian. This argument compares both exponents, not just a chosen representation.

   Source: `DeuringOrd.Poly.exists_expand_wronskian_ne_zero; expand_exponent_unique`.

2. The imported x-coordinate representation and degree-inequality results give each nonzero rational homomorphism an IsXPair: a coprime nonconstant x-coordinate fraction valid off finitely many source x-coordinates. Define its height h(f) as the exponent from step 1. Every x in k occurs on the elliptic Weierstrass curve because its equation is monic quadratic in y over an algebraically closed field; ellipticity makes these points nonsingular. Consequently two x-pairs for the same map agree off a finite subset of the infinite field k, and cross-multiplication gives equality of polynomials. Step 1 then gives well-definedness of height. Heights add under composition. To prove this, homogenize the residual numerator and denominator of the outer fraction, substitute the inner residual pair with the required Frobenius twist of coefficients, and use the imported coprime/nonzero-Wronskian composition theorem. Its resulting pair is expanded by p^(a+b). The exceptional set consists of the inner exceptional set and preimages of the finitely many outer exceptional x-values. Each such preimage is finite, since a nonconstant reduced fraction cannot equal a constant identically. Thus the composition satisfies the exact IsXPair definition and has height a+b.

   Source: `DeuringOrd.IsXPair; exists_isXPair; IsXPair.mul_eq_mul; HasHeight; exists_hasHeight; hasHeight_unique; HasHeight.comp`.

3. For every nonzero integer n, the division polynomials Phi_n and PsiSq_n give a coprime x-pair for [n]. Their degree properties give deg(Phi_n)=|n|^2>0 and PsiSq_n nonzero, so there is an affine point outside the finite denominator-root set whose image under [n] is affine and therefore nonzero. Hence [n] is not the zero endomorphism: integer scalar action on A is faithful. For n=p the imported division-polynomial Wronskian identity and char(k)=p force the Wronskian of Phi_p,PsiSq_p to vanish; the other factor Psi2Sq is nonzero by ellipticity. Contract once, then apply step 1. We obtain a height pi>=1 for [p], represented by Phi_p=r1(X^(p^pi)), PsiSq_p=r2(X^(p^pi)), with r1,r2 coprime and with nonzero Wronskian. This applies in characteristic 2 as well; no division by 2 or 3 occurs.

   Source: `DeuringOrd.isXPair_zsmul; exists_zsmul_ne_zero; eq_zero_of_forall_zsmul_eq_zero; exists_mulP_core`.

4. Suppose beta satisfies beta^2-t beta+[q]=0 and also c beta=[e] for integers c!=0,e. Multiply the quadratic relation by c^2 and substitute the scalar relation, obtaining [e^2-t e c+q c^2]=0. Faithfulness from step 3 makes that integer zero. Reduce e/c by their integer gcd, writing e=g e1 and c=g c1 with c1,e1 coprime. The resulting equation implies c1 divides e1^2, so coprimality makes c1 a unit, namely +/-1. Thus e1*c1 is an integer root of X^2-tX+q. The original no-integer-root hypothesis therefore excludes every nonzero integer scalar relation for beta. In particular beta!=0 and beta!=[t]. This step does not cancel scalar multiplication on arbitrary individual torsion points.

   Source: `DeuringOrd.Poly.exists_int_root; DeuringOrd.exists_int_root_of_zsmul_eq`.

5. Assume toward contradiction that every point killed by the natural-number scalar p is zero. Let alpha be a nonzero rational endomorphism satisfying the same irreducible quadratic relation and having height a with 2a>=pi. Rational nonzero endomorphisms are surjective by the imported theorem, so alpha^2 is nonzero and has height 2a. Its x-coordinate fraction can therefore be written as an expansion by p^pi of a coprime pair. Let rho=[p] and delta=alpha^2. The assumed trivial p-kernel implies ker(rho) is contained in ker(delta). Together with the expanded x-coordinate representations and the residual nonzero Wronskian for rho from step 3, these are exactly the hypotheses of the imported rational-factorization theorem. It supplies a rational gamma with alpha^2=gamma composed with [p], equivalently alpha^2=p gamma. The proof does not assume that a pointwise inverse to [p] is rational.

   Source: `DeuringOrd.core, through hgammaeq and hgammap`.

6. Write q=p q1. The quadratic relation and alpha^2=p gamma imply t alpha=p(gamma+[q1]). Since p is prime and does not divide t, choose integers u,v with u p+v t=1. Set eta=v(gamma+[q1])+u alpha. Closure of rational homomorphisms under addition and integer scaling makes eta rational, and multiplying this expression by p gives p eta=alpha. Since alpha is nonzero, eta is nonzero. This is a Bezout construction of a rational p-division of alpha, not division by p on the point group.

   Source: `DeuringOrd.core, hgamma'apply through hbeta_gamma' (Lean names hgamma'apply and hbeta_gamma' are explanatory transliterations of the Greek identifiers)`.

7. Apply the imported dual trace theorem to eta. It supplies a rational sigma and integers t',n' (n'>0) with eta+sigma=[t'] and sigma composed with eta=[n']. Evaluating the sum on eta(P) gives eta^2=t' eta-[n']. Combining this relation, alpha=p eta, and alpha^2-t alpha+[q]=0 yields c alpha=[e], where c=p^2 t'-tp and e=p(p^2 n'-q), as in the source's final linear combination. If c=0, cancellation in the integer ring (not on A) gives t=p t', contrary to p not dividing t. Therefore c!=0. Step 4 gives an integer root of the forbidden quadratic, a contradiction. This proves the core contradiction whenever 2h(alpha)>=pi.

   Source: `DeuringOrd.core, hdual/hsum, hgamma'sq, hc, final exists_int_root_of_zsmul_eq call`.

8. For the original beta, put beta'=[t]-beta. Rational closure gives beta' rational, direct expansion gives beta'^2-t beta'+[q]=0, and step 4 shows that beta and beta' are both nonzero. Write their heights as a and b. The hypothesis on roots implies q!=0 by evaluating at zero; writing q=p q1 therefore gives q1!=0. Let mu=[q1], which is nonzero by step 3 and rational by closure, and let its height be c0>=0. The quadratic identity implies beta composed with beta'=[q]=mu composed with [p]. Uniqueness and additivity of height give a+b=c0+pi, hence a+b>=pi. If 2a>=pi, apply steps 5-7 to beta. Otherwise 2b>=pi, and apply the same core contradiction to beta', which has precisely the same t,q and no-integer-root hypotheses. Both cases contradict the assumption that the p-kernel is trivial. Thus some T in the exact frozen point type is nonzero and satisfies the natural-number equation p • T=0.

   Source: `DeuringOrd.main`.

## Imported hypotheses and proof boundary

The polynomial contraction lemmas require a field of prime characteristic, coprime numerator and denominator, and positive maximum degree; height composition additionally requires algebraic closure and the stated nonsingular coordinate representations. Rational-map representation, surjectivity, division-polynomial and duality lemmas are applied to the same elliptic W over algebraically closed k. Factorization requires two nonzero rational homomorphisms, kernel inclusion, a finite exceptional set, common p-power coordinate expansions, coprime residual pairs, and a nonzero Wronskian for the divisor map; step 5 supplies each hypothesis. Dual trace existence requires a nonzero rational endomorphism; step 6 supplies it. These imported results are verified Lean proofs in the pinned closure, not additional assumptions. No unsupported step is being filled by the geometric obligations G, D, or K.

## Provenance and validation scope

The source is the 46-module closure in `/mnt/data/zhengyang-workspace/fermat-example/.humanize/upstream-reference/6e837e75355538c7f80bab5b956861e86c4eacc2`, pinned at revision `6e837e75355538c7f80bab5b956861e86c4eacc2`. The root module is `P2M/Sol/S_WeierstrassCurve_exists_ne_zero_and_char_nsmul_eq_zero_of_comp_self_add_smul_eq_smul_of_dvd_of_not_dvd.lean`. The manifest copied to `third_party/fermats-last-theorem/import-manifest.json` records every source SHA-256 and Git blob. The existing rationality definition must agree byte for byte. The global root declaration in Submission.lean applies the upstream solution to every original hypothesis. The selected root is the global WeierstrassCurve declaration, not a declaration inside namespace Submission.

The operator reconstruction supplied useful prose, checked here against the actual Lean definitions and core/main proofs; that draft and the earlier diagnostic are not acceptance records. This candidate still requires its own warning-fatal build, exact-contract comparator, axiom/kernel checks, and independent reviewer. The outer controller owns the final reviewer comparator, issue/PR lifecycle, publication, and DAG transition.

## Publication artifact and review boundary

This is the required publication artifact for run `20261006T035907Z-f6caab1a65`.
Its numbered argument is carried forward from
`proofs/deuring-criterion/root-height-proof.md`; that original document and all
historical review records remain unchanged. The actual root wrapper and its
46-module upstream closure are unchanged. This repair also removes two duplicate
placeholder root stubs and a redundant triply nested finite-kernel child copy
found in the inherited candidate; none is used in the proof. The original child
declaration is preserved. Relative to reviewed commit
`0282bd68f3c063655577284abe3fb609b2590906`, one extra `namespace Submission`
opening was also removed so the two arithmetic children retain their exact
comparator-approved names, `Submission.deuring_no_integer_scalar_relation_f6caab1a65`
and `Submission.deuring_trace_norm_unique_f6caab1a65`. Their types and proof bodies
are unchanged. No new named helper theorem is introduced.

A reviewer must read this file from the exact committed candidate, compare each
step with the Lean source, and record this path's Git blob only after independent
review. The author does not set `publication_proof_reviewed` or claim the earlier
review of the alternative path satisfies the committed-blob publication gate.
The independent comparator rerun and final acceptance remain outer-controller
work after this implementation handoff.