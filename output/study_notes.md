# Introductory Calculus Lecture 1: Syllabus and Review

## Course Logistics and Structure
This lecture provided an overview of the course logistics. The lecturer is Dan Ciubotaru. All lecture notes, written by Cath Wilkins, and problem sheets are available online. Students will participate in 4 tutorials throughout the term to discuss problem sheet solutions.

### Key Points
- The course consists of 16 lectures (Mondays and Wednesdays at 10 AM).
- There are 8 compulsory problem sheets, with the first two already online.
- Recommended Text: *Mathematical Methods in the Physical Sciences* by Mary Boas.

> [!NOTE]
> Important: Ensure you locate the online lecture notes immediately.

> [!NOTE]
> Lecturer Contact: Call the lecturer 'Dan'.

## Syllabus Breakdown
The first half of the course focuses on Differential Equations (ODEs and PDEs). The course then shifts to Integral Calculus, specifically Line and Double Integrals. The final segment introduces multivariable calculus concepts essential for later modules, including surface analysis, the gradient normal vector, Taylor's theorem in two variables, critical points, and the method of Lagrange multipliers. This course is crucial for subsequent modules like Dynamics, Analysis 2, and PDEs.

### Key Points
- Part 1: Differential Equations (ODEs and PDEs) (7-8 lectures).
- Part 2: Line and Double Integrals (3 lectures).
- Part 3: Calculus of Functions in Two Variables (Multivariable introduction).

> [!NOTE]
> Focus Area: The content closely interacts with Multivariable Calculus and Dynamics.

> [!NOTE]
> Course Status: This is a useful and mandatory course.

## Introduction to Differential Equations and Applications
The simplest ODE, $\\frac{dy}{dx} = f(x)$, is solved by direct integration. In physical systems, such as mechanics, Newton's Second Law ($\\mathbf{F}=m\\mathbf{a}$) yields a second-order ODE since acceleration $\\mathbf{a} = \\frac{d^2\\mathbf{r}}{dt^2}$. For an RLC circuit (Resistor R, Inductor L, Capacitor C) subject to voltage $V(t)$, applying Kirchhoff's Law results in the second-order linear ODE:

$$\\text{L}\\frac{d^2Q}{dt^2} + R\\frac{dQ}{dt} + \\frac{1}{C}Q = V(t)$$

where Q is the charge on the capacitor.

### Key Points
- An Ordinary Differential Equation (ODE) involves an independent variable, a function, and its derivatives.
- The Order of an ODE is defined by the order of the highest derivative.
- ODEs are essential for modeling physical systems (e.g., Newton's Second Law, RLC Circuits).

> [!NOTE]
> ODE Definition: Equations involving $x, y(x),$ and $y'(x)$ only.

> [!NOTE]
> Physics Link: The RLC circuit equation is a prime example of damped harmonic motion.

## Review: Integration by Parts and Separable Equations
We revisited Integration by Parts (IBP), derived from the product rule $(fg)' = f'g + fg'$. The crucial formula is:

$$\\int f g' \, dx = f g - \\int f' g \, dx$$

For **Separable Equations**, $dy/dx = a(x)b(y)$, the procedure is to separate the variables and integrate each side:

$$\\int \\frac{1}{b(y)} \, dy = \\int a(x) \, dx$$

An example of a reduction formula derived using IBP was given for $I_n = \\int \\cos^n(x) \, dx$:

$$\\text{I}_n = \\frac{1}{n}\\cos^{n-1}(x)\\sin(x) + \\frac{n-1}{n}\\text{I}_{n-2}$$

### Key Points
- Integration by Parts (IBP) converts the integral of a product into a simpler integral.
- Separable Equations can be solved by isolating $x$ and $y$ variables before integration.
- Reduction formulas recursively simplify certain complex integrals (e.g., $\\int \\cos^n(x) \, dx$).

> [!NOTE]
> Crucial Skill: Practice choosing which function is $f$ and which is $g'$ (or $u$ and $dv$) in IBP.

> [!NOTE]
> Example Solution: The general solution for the separable equation $x(y^2-1) + y(x^2-1)(dy/dx) = 0$ is $(1-y^2)(1-x^2) = C$.

## Glossary
- **Problem Sheets**
- **Tutorials**
- **Recommended Reading**
- **ODEs**
- **PDEs**
- **Line Integrals**
- **Lagrange Multipliers**
- **Taylor's Theorem**
- **Order of ODE**
- **RLC Circuit**
- **Kirchhoff's Law**
- **Radioactive Decay**
- **Integration by Parts**
- **Separable Equations**
- **Reduction Formula**
- **Product Rule**
